"""Explicitly registered tools for agents.

An agent can only call the tools named in its registry entry, through a
``ToolBox`` bound to one workflow. Every tool:

* takes the workspace from the workflow row, never from model output;
* filters every query by that workspace;
* goes through an existing service (brand context, research engine, content
  studio, analytics queries).

There is deliberately no tool for publishing, scheduling, approving, deleting,
changing roles or credentials, HTTP requests, shell commands or SQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session as DBSession

from app.core.config import Settings
from app.integrations.research.services.research_service import ResearchEngineService
from app.models import (
    AgentWorkflow,
    Brand,
    ContentDraft,
    ContentProject,
    ResearchProject,
    ResearchReport,
    ResearchSource,
    User,
    WorkspaceMembership,
)
from app.services.analytics import queries as analytics_queries
from app.services.analytics.summaries import compact_performance
from app.services.automation import events as automation_events
from app.services.brand_context import brand_context_service
from app.services.content_studio import ContentStudioService

MAX_SOURCES = 12
MAX_SNIPPET_CHARS = 500


class ToolError(Exception):
    """A tool could not complete (missing record, no access, not configured)."""


class UnknownToolError(ToolError):
    pass


class ToolNotAllowedError(ToolError):
    pass


@dataclass
class AgentContext:
    """Everything an agent may use. Built by the orchestrator for one workflow."""

    db: DBSession
    workflow: AgentWorkflow
    actor: User
    membership: WorkspaceMembership
    settings: Settings
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def workspace_id(self) -> UUID:
        return self.workflow.workspace_id


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    access: str  # "read" or "write"
    handler: Callable[..., Any]


TOOLS: dict[str, ToolSpec] = {}


def register_tool(name: str, description: str, *, access: str = "read") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    if access not in {"read", "write"}:
        raise ValueError("Tool access must be 'read' or 'write'.")

    def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
        if name in TOOLS:
            raise ValueError(f"Tool {name} is already registered.")
        TOOLS[name] = ToolSpec(name=name, description=description, access=access, handler=handler)
        return handler

    return decorator


class ToolBox:
    """The tools one agent is allowed to call during one execution."""

    def __init__(self, ctx: AgentContext, allowed: tuple[str, ...], *, caller: str) -> None:
        self._ctx = ctx
        self._allowed = frozenset(allowed)
        self._caller = caller

    @property
    def allowed(self) -> frozenset[str]:
        return self._allowed

    def call(self, name: str, **kwargs: Any) -> Any:
        spec = TOOLS.get(name)
        if spec is None:
            raise UnknownToolError(f"Tool '{name}' does not exist.")
        if name not in self._allowed:
            raise ToolNotAllowedError(f"Agent '{self._caller}' is not allowed to use tool '{name}'.")
        self._ctx.tool_calls.append({"caller": self._caller, "tool": name, "access": spec.access})
        return spec.handler(self._ctx, **kwargs)


def _uuid(value: Any, label: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise ToolError(f"{label} is not a valid id.") from exc


def _short(value: str | None, limit: int) -> str:
    return " ".join((value or "").split())[:limit]


# Read tools -----------------------------------------------------------------------


@register_tool("get_brand_profile", "Brand profile, voice, audiences, content pillars, goals and policies.")
def get_brand_profile(ctx: AgentContext, *, brand_id: Any) -> dict[str, Any]:
    try:
        context = brand_context_service.get_brand_context(
            _uuid(brand_id, "The brand"), ctx.workspace_id, ctx.actor, ctx.db
        )
    except HTTPException as exc:
        raise ToolError("The brand was not found in this workspace or is archived.") from exc
    return context.model_dump(mode="json")


@register_tool("get_research", "Research reports and source records from this workspace.")
def get_research(ctx: AgentContext, *, research_ids: list[Any]) -> dict[str, Any]:
    ids = [_uuid(item, "A research project") for item in research_ids]
    if not ids:
        return {"projects": [], "sources": []}
    projects = (
        ctx.db.query(ResearchProject)
        .filter(ResearchProject.workspace_id == ctx.workspace_id, ResearchProject.id.in_(ids))
        .all()
    )
    if len(projects) != len(set(ids)):
        raise ToolError("A selected research project was not found in this workspace.")
    by_id = {project.id: project for project in projects}
    result: dict[str, Any] = {"projects": [], "sources": []}
    for research_id in dict.fromkeys(ids):
        project = by_id[research_id]
        report = ctx.db.query(ResearchReport).filter(ResearchReport.research_id == project.id).first()
        result["projects"].append(
            {
                "id": str(project.id),
                "title": project.title,
                "research_question": project.research_question,
                "status": project.status,
                "report_id": str(report.id) if report else None,
                "report": {
                    "executive_summary": report.executive_summary,
                    "key_findings": list(report.key_findings or []),
                    "trends": list(report.trends or []),
                    "opportunities": list(report.opportunities or []),
                    "audience_insights": list(report.audience_insights or []),
                    "competitor_insights": list(report.competitor_insights or []),
                    "content_angles": list(report.content_angles or []),
                    "limitations": list(report.limitations or []),
                }
                if report
                else None,
            }
        )
        sources = (
            ctx.db.query(ResearchSource)
            .filter(ResearchSource.research_id == project.id)
            .order_by(ResearchSource.created_at.asc())
            .limit(MAX_SOURCES)
            .all()
        )
        for source in sources:
            result["sources"].append(
                {
                    "source_id": str(source.id),
                    "research_id": str(project.id),
                    "title": _short(source.title, 200),
                    "url": source.url,
                    "domain": source.domain,
                    # Retrieved web text: untrusted. Agents quote it as data only.
                    "snippet": _short(source.extracted_content or source.snippet, MAX_SNIPPET_CHARS),
                }
            )
    result["sources"] = result["sources"][:MAX_SOURCES]
    return result


@register_tool("get_content_project", "A content project and its drafts (optionally approved content only).")
def get_content_project(ctx: AgentContext, *, project_id: Any, approved_only: bool = False) -> dict[str, Any]:
    project = (
        ctx.db.query(ContentProject)
        .filter(ContentProject.id == _uuid(project_id, "The content item"), ContentProject.workspace_id == ctx.workspace_id)
        .first()
    )
    if project is None:
        raise ToolError("The content item was not found in this workspace.")
    if approved_only and project.status != "approved":
        raise ToolError("Only approved content can be used as a source. Approve this content first.")
    drafts = ctx.db.query(ContentDraft).filter(ContentDraft.project_id == project.id).all()
    return {
        "project_id": str(project.id),
        "brand_id": str(project.brand_id) if project.brand_id else None,
        "title": project.title,
        "topic": project.topic,
        "objective": project.objective,
        "status": project.status,
        "drafts": [
            {
                "platform": draft.platform,
                "title": draft.title,
                "hook": draft.hook,
                "body": draft.body,
                "cta": draft.cta,
                "hashtags": list(draft.hashtags or []),
                "status": draft.status,
            }
            for draft in drafts
        ],
    }


@register_tool("get_analytics", "Measured post performance for this workspace (Phase 9 analytics).")
def get_analytics(ctx: AgentContext, *, days: int = 30, brand_id: Any = None) -> dict[str, Any]:
    days = max(7, min(90, int(days)))
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days - 1)
    brand_uuid = _uuid(brand_id, "The brand") if brand_id else None
    if brand_uuid is not None:
        exists = ctx.db.query(Brand.id).filter(Brand.id == brand_uuid, Brand.workspace_id == ctx.workspace_id).first()
        if exists is None:
            raise ToolError("The brand was not found in this workspace.")
    filters = analytics_queries.resolve_accounts(
        ctx.db, analytics_queries.AnalyticsFilters(ctx.workspace_id, start, end, brand_id=brand_uuid)
    )
    performance = analytics_queries.content_performance(ctx.db, filters)
    data = compact_performance(performance)
    data["connected_accounts"] = len(filters.accounts)
    data["metric_notes"] = list(performance.get("notes") or [])
    return data


# Controlled write tools ------------------------------------------------------------


@register_tool(
    "run_research",
    "Create and run a research project with the Phase 4 research engine and its search provider.",
    access="write",
)
def run_research(ctx: AgentContext, *, question: str, brand_id: Any = None) -> dict[str, Any]:
    service = ResearchEngineService(ctx.db)
    try:
        provider = service.ensure_search_provider()
    except RuntimeError as exc:
        # Nothing is created when no search provider is configured.
        return {"research_id": None, "provider_configured": False, "source_count": 0, "message": str(exc)}
    brand_uuid = _uuid(brand_id, "The brand") if brand_id else None
    if brand_uuid is not None:
        exists = ctx.db.query(Brand.id).filter(Brand.id == brand_uuid, Brand.workspace_id == ctx.workspace_id).first()
        if exists is None:
            raise ToolError("The brand was not found in this workspace.")
    cleaned = " ".join(question.split())
    project = ResearchProject(
        workspace_id=ctx.workspace_id,
        brand_id=brand_uuid,
        created_by=ctx.actor.id,
        title=cleaned[:200] or "Agent research",
        research_question=cleaned[:2000],
        category="AI agent research",
        language="en",
        research_depth="standard",
        status="SEARCHING",
        current_stage="SEARCHING",
    )
    ctx.db.add(project)
    ctx.db.flush()
    service.create_queries(project)
    try:
        results = service.search(project)
    except RuntimeError as exc:
        project.status = project.current_stage = "FAILED"
        ctx.db.flush()
        return {"research_id": None, "provider_configured": False, "source_count": 0, "message": str(exc)}
    for result in results:
        service.persist_source_result(project, result)
    service.create_default_report(project, generated_by_model=provider.name)
    project.status = project.current_stage = "COMPLETED"
    project.completed_at = datetime.now(timezone.utc)
    service.create_usage_log(project, provider_name=provider.name, status="COMPLETED", search_requests=len(project.queries))
    ctx.db.flush()
    return {
        "research_id": str(project.id),
        "provider_configured": True,
        "source_count": len(results),
        "message": None if results else "The search provider returned no usable sources.",
    }


@register_tool(
    "create_content_draft",
    "Create a draft content project in the content studio. Used only when a person accepts an output.",
    access="write",
)
def create_content_draft(
    ctx: AgentContext,
    *,
    title: str,
    topic: str | None,
    objective: str | None,
    brand_id: Any,
    versions: list[dict[str, Any]],
    research_report_id: Any = None,
    content_pillar: str | None = None,
    platforms: list[str] | None = None,
) -> dict[str, Any]:
    """Always creates status ``draft``. Approval, scheduling and publishing stay with people."""
    selected = list(dict.fromkeys([str(v["platform"]) for v in versions] or list(platforms or [])))
    if not selected or any(platform not in {"facebook", "instagram"} for platform in selected):
        raise ToolError("Select Facebook and/or Instagram for the draft.")
    brand_uuid = _uuid(brand_id, "The brand") if brand_id else None
    if brand_uuid is not None:
        exists = ctx.db.query(Brand.id).filter(Brand.id == brand_uuid, Brand.workspace_id == ctx.workspace_id).first()
        if exists is None:
            brand_uuid = None
    report_uuid = None
    if research_report_id:
        report = (
            ctx.db.query(ResearchReport.id)
            .join(ResearchProject, ResearchProject.id == ResearchReport.research_id)
            .filter(ResearchReport.id == _uuid(research_report_id, "The research report"), ResearchProject.workspace_id == ctx.workspace_id)
            .first()
        )
        report_uuid = report.id if report else None
    studio = ContentStudioService(ctx.db)
    for version in versions:
        errors = studio.validate_platform(str(version["platform"]), version)
        if errors:
            raise ToolError("; ".join(errors))
    project = ContentProject(
        workspace_id=ctx.workspace_id,
        brand_id=brand_uuid,
        created_by=ctx.actor.id,
        title=(title or "AI agent draft").strip()[:200],
        topic=(topic or None) and topic[:3000],
        objective=(objective or None) and objective[:3000],
        content_type="text_post",
        selected_platforms=selected,
        content_pillar=(content_pillar or None) and content_pillar[:160],
        research_report_id=report_uuid,
        status="draft",
        labels=["ai-agents"],
    )
    ctx.db.add(project)
    ctx.db.flush()
    draft_ids: dict[str, str] = {}
    for version in versions:
        draft = studio.create_draft(project, platform=str(version["platform"]))
        draft.title = project.title
        draft.hook = version.get("hook") or ""
        draft.body = version.get("body") or ""
        draft.cta = version.get("cta") or ""
        draft.hashtags = list(version.get("hashtags") or [])
        draft.ai_generated = True
        studio.create_version(draft, change_reason="Accepted from an AI agent workflow", created_by=ctx.actor.id)
        draft_ids[draft.platform] = str(draft.id)
    automation_events.emit_content_created(ctx.db, project, actor_user_id=ctx.actor.id)
    return {"project_id": str(project.id), "draft_ids": draft_ids, "status": project.status}


READ_TOOLS: tuple[str, ...] = tuple(name for name, spec in TOOLS.items() if spec.access == "read")


def describe_tools(names: tuple[str, ...]) -> list[dict[str, str]]:
    return [{"name": name, "description": TOOLS[name].description, "access": TOOLS[name].access} for name in names]
