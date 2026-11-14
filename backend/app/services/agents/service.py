"""Human review of workflow output: accept, reject, request a revision; plus dashboard statistics.

Accepting is the only path from an agent's output into the content studio, and
it is always a person's action. The result is an ordinary ``draft`` content
project owned by that person; approval, scheduling and publishing keep working
exactly as in Phases 5-8.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.models import AgentWorkflow, ContentProject, ResearchReport, User, WorkspaceMembership
from app.services.agents import orchestrator as O
from app.services.agents import workflows as W
from app.services.agents.tools import AgentContext, ToolBox
from app.services.audit import record_audit
from app.services.publishing.queue import enqueue_publication

HUMAN_REVIEW = "human_review"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_reviewable(workflow: AgentWorkflow) -> dict[str, Any]:
    if workflow.status != "succeeded" or not workflow.final_output:
        raise O.WorkflowStateError("Only a finished workflow can be reviewed.")
    return workflow.final_output


def _first_report_id(db: DBSession, workflow: AgentWorkflow, research_ids: list[str]) -> UUID | None:
    for research_id in research_ids:
        try:
            report = db.query(ResearchReport.id).filter(ResearchReport.research_id == UUID(str(research_id))).first()
        except ValueError:
            continue
        if report is not None:
            return report.id
    return None


def accept_output(
    db: DBSession,
    workflow: AgentWorkflow,
    *,
    user: User,
    membership: WorkspaceMembership,
    idea_index: int | None = None,
) -> dict[str, Any]:
    """Save the reviewed draft (or one content idea) as a draft content project."""
    output = _require_reviewable(workflow)
    definition = W.get_workflow(workflow.workflow_type)
    if definition.accept_mode is None:
        raise O.WorkflowStateError("This workflow produces recommendations; there is no draft to accept.")
    if workflow.review_status == "rejected":
        raise O.WorkflowStateError("This output was rejected. Run the workflow again to get a new draft.")
    ctx = AgentContext(db=db, workflow=workflow, actor=user, membership=membership, settings=get_settings())
    tools = ToolBox(ctx, ("create_content_draft",), caller=HUMAN_REVIEW)
    accepted_ideas = dict(output.get("accepted_idea_projects") or {})
    brand_id = workflow.brand_id
    source_project_id = (workflow.input_data or {}).get("content_project_id")
    if brand_id is None and source_project_id:
        source = (
            db.query(ContentProject.brand_id)
            .filter(ContentProject.id == UUID(source_project_id), ContentProject.workspace_id == workflow.workspace_id)
            .first()
        )
        brand_id = source.brand_id if source else None

    if definition.accept_mode == "draft":
        if workflow.review_status == "accepted":
            raise O.WorkflowStateError("This draft was already accepted into the content studio.")
        draft = output.get("content_draft") or {}
        versions = [item for item in draft.get("versions") or [] if isinstance(item, dict)]
        if not versions:
            raise O.WorkflowStateError("The workflow output has no draft to accept.")
        created = tools.call(
            "create_content_draft",
            title=draft.get("title") or workflow.name,
            topic=workflow.task,
            objective=None,
            brand_id=brand_id,
            versions=versions,
            research_report_id=_first_report_id(db, workflow, list(output.get("research_ids") or [])),
        )
    else:
        ideas = output.get("content_ideas") or []
        if idea_index is None or not 0 <= idea_index < len(ideas):
            raise W.WorkflowInputError("Choose which content idea to accept.")
        if str(idea_index) in accepted_ideas:
            raise O.WorkflowStateError("This content idea was already added to the content studio.")
        idea = ideas[idea_index]
        created = tools.call(
            "create_content_draft",
            title=idea.get("title") or workflow.name,
            topic=idea.get("description"),
            objective=idea.get("objective"),
            brand_id=brand_id,
            versions=[],
            platforms=[idea.get("platform")],
            content_pillar=idea.get("content_pillar"),
            research_report_id=_first_report_id(db, workflow, list((output.get("research_findings") or {}).get("research_ids") or [])),
        )
        accepted_ideas[str(idea_index)] = created["project_id"]
        workflow.final_output = {**output, "accepted_idea_projects": accepted_ideas}

    workflow.review_status = "accepted"
    workflow.reviewed_by = user.id
    workflow.reviewed_at = utc_now()
    workflow.accepted_project_id = UUID(created["project_id"])
    record_audit(
        db,
        action="agent_workflow.output_accepted",
        resource_type="agent_workflow",
        actor_user_id=user.id,
        workspace_id=workflow.workspace_id,
        resource_id=workflow.id,
        metadata={"content_project_id": created["project_id"], "mode": definition.accept_mode, "idea_index": idea_index},
    )
    db.commit()
    db.refresh(workflow)
    return created


def reject_output(db: DBSession, workflow: AgentWorkflow, *, user: User, reason: str | None) -> AgentWorkflow:
    _require_reviewable(workflow)
    if workflow.review_status != "pending":
        raise O.WorkflowStateError("This output was already reviewed.")
    workflow.review_status = "rejected"
    workflow.review_note = (reason or "").strip()[:1000] or None
    workflow.reviewed_by = user.id
    workflow.reviewed_at = utc_now()
    record_audit(
        db,
        action="agent_workflow.output_rejected",
        resource_type="agent_workflow",
        actor_user_id=user.id,
        workspace_id=workflow.workspace_id,
        resource_id=workflow.id,
    )
    db.commit()
    db.refresh(workflow)
    return workflow


def request_revision(db: DBSession, workflow: AgentWorkflow, *, user: User, feedback: str) -> AgentWorkflow:
    """Queue one more writer + reviewers round with the person's feedback. Bounded by AGENT_MAX_REVISIONS."""
    settings = get_settings()
    _require_reviewable(workflow)
    definition = W.get_workflow(workflow.workflow_type)
    if not definition.revision_steps:
        raise O.WorkflowStateError("This workflow does not produce a draft that can be revised.")
    if workflow.review_status != "pending":
        raise O.WorkflowStateError("This output was already reviewed. Run the workflow again for a new draft.")
    if workflow.revision_count >= settings.agent_max_revisions:
        raise O.WorkflowLimitError(
            f"The limit of {settings.agent_max_revisions} revision round(s) was reached. Edit the draft in the content studio instead."
        )
    if not settings.agents_enabled:
        raise O.WorkflowStateError("AI agent workflows are disabled on this server.")
    if O.active_workflow_count(db, workflow.workspace_id, exclude=workflow.id) >= settings.agent_max_active_workflows:
        raise O.WorkflowLimitError("Too many workflows are in progress in this workspace. Try again when one finishes.")
    cleaned = " ".join(feedback.split())[:1000]
    round_number = O.append_revision_round(db, workflow, definition, feedback=cleaned, auto=False, reasons=[cleaned])
    workflow.status = "pending"
    workflow.completed_at = None
    workflow.review_status = None
    workflow.deadline_at = None
    workflow.next_attempt_at = None
    workflow.cancel_requested = False
    workflow.error_message = None
    record_audit(
        db,
        action="agent_workflow.revision_requested",
        resource_type="agent_workflow",
        actor_user_id=user.id,
        workspace_id=workflow.workspace_id,
        resource_id=workflow.id,
        metadata={"round": round_number},
    )
    db.commit()
    db.refresh(workflow)
    enqueue_publication(workflow.id)
    return workflow


def workspace_stats(db: DBSession, workspace_id: UUID, *, days: int = 30) -> dict[str, Any]:
    since = utc_now() - timedelta(days=days)
    rows = (
        db.query(
            AgentWorkflow.status,
            func.count(AgentWorkflow.id),
            func.coalesce(func.sum(AgentWorkflow.agent_call_count), 0),
            func.coalesce(func.sum(AgentWorkflow.total_tokens), 0),
        )
        .filter(AgentWorkflow.workspace_id == workspace_id, AgentWorkflow.created_at >= since)
        .group_by(AgentWorkflow.status)
        .all()
    )
    counts = {status: 0 for status in ("pending", "running", "succeeded", "failed", "cancelled")}
    calls = tokens = 0
    for status, count, call_sum, token_sum in rows:
        counts[status] = int(count)
        calls += int(call_sum or 0)
        tokens += int(token_sum or 0)
    settings = get_settings()
    return {
        "days": days,
        "counts": counts,
        "total": sum(counts.values()),
        "active": counts["pending"] + counts["running"],
        "agent_calls": calls,
        "total_tokens": tokens,
        "limits": limits(settings),
    }


def limits(settings=None) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        "enabled": settings.agents_enabled,
        "max_calls_per_workflow": settings.agent_max_calls_per_workflow,
        "max_workflow_seconds": settings.agent_max_workflow_seconds,
        "step_timeout_seconds": settings.agent_step_timeout_seconds,
        "max_step_attempts": settings.agent_max_step_attempts,
        "max_auto_revisions": settings.agent_max_auto_revisions,
        "max_revisions": settings.agent_max_revisions,
        "max_parallel_calls": settings.agent_max_parallel_calls,
        "max_active_workflows": settings.agent_max_active_workflows,
        "max_workflows_per_hour": settings.agent_max_workflows_per_hour,
    }
