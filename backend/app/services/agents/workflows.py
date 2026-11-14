"""Predefined multi-agent workflows.

A workflow is a fixed list of steps with dependencies. Users choose a workflow
and supply inputs; they cannot define steps, prompts or tools. Step kinds:

``context``  the orchestrator checks and summarizes records through read-only tools
``agent``    one registered agent runs (one Groq call)
``compile``  the orchestrator assembles the deliverable from validated step outputs

Steps that share a ``parallel_group`` are independent of each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from app.core.config import Settings
from app.models import AgentWorkflow, Brand, ContentProject, ResearchProject
from app.services.agents import agents as _agents  # noqa: F401 - registers the agents
from app.services.agents.registry import ORCHESTRATOR_KEY, get_agent
from app.services.agents.schemas import PLATFORMS
from app.services.agents.tools import AgentContext, ToolBox

HUMAN_REVIEW_NOTE = (
    "AI-generated output for human review. Nothing was saved to the content studio, approved, scheduled or published."
)


class WorkflowError(Exception):
    pass


class UnknownWorkflowError(WorkflowError):
    pass


class WorkflowInputError(WorkflowError):
    """Invalid or inaccessible input. ``not_found`` marks ids outside the workspace."""

    def __init__(self, message: str, *, not_found: bool = False) -> None:
        super().__init__(message)
        self.not_found = not_found


@dataclass
class RunState:
    """Validated outputs of the steps that already succeeded, for building the next step's input."""

    workflow: AgentWorkflow
    inputs: dict[str, Any]
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    envelopes: dict[str, dict[str, Any]] = field(default_factory=dict)
    rounds: dict[str, tuple[str, int]] = field(default_factory=dict)  # step_key -> (base_key, round)
    round: int = 0
    feedback: str | None = None

    def latest_key(self, base_key: str, *, before_round: int | None = None) -> str | None:
        limit = self.round if before_round is None else before_round - 1
        best: tuple[int, str] | None = None
        for step_key, (base, round_number) in self.rounds.items():
            if base == base_key and round_number <= limit and (best is None or round_number > best[0]):
                best = (round_number, step_key)
        return best[1] if best else None

    def latest(self, base_key: str, *, before_round: int | None = None) -> dict[str, Any] | None:
        key = self.latest_key(base_key, before_round=before_round)
        return self.results.get(key) if key else None

    def envelope(self, base_key: str) -> dict[str, Any] | None:
        key = self.latest_key(base_key)
        return self.envelopes.get(key) if key else None


@dataclass(frozen=True)
class StepDef:
    key: str
    kind: str
    label: str
    agent_key: str = ORCHESTRATOR_KEY
    depends_on: tuple[str, ...] = ()
    parallel_group: str | None = None
    build_input: Callable[[RunState], dict[str, Any]] | None = None
    run: Callable[[AgentContext, ToolBox, RunState], dict[str, Any]] | None = None


@dataclass(frozen=True)
class WorkflowDef:
    key: str
    name: str
    description: str
    deliverables: tuple[str, ...]
    steps: tuple[StepDef, ...]
    requires: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    revision_steps: tuple[str, ...] = ()
    review_gate: Callable[[RunState, Settings], list[str]] | None = None
    accept_mode: str | None = None  # "draft", "idea" or None

    def step(self, key: str) -> StepDef:
        for item in self.steps:
            if item.key == key:
                return item
        raise UnknownWorkflowError(f"Workflow {self.key} has no step {key}.")

    @property
    def agent_keys(self) -> list[str]:
        return list(dict.fromkeys(item.agent_key for item in self.steps if item.kind == "agent"))


# Helpers --------------------------------------------------------------------------


def _pick(source: dict[str, Any] | None, *keys: str) -> dict[str, Any]:
    return {key: source.get(key) for key in keys} if source else {}


def _research_ids(state: RunState) -> list[str]:
    ids = list(state.inputs.get("research_ids") or [])
    for base in ("research", "research_context"):
        ids.extend((state.latest(base) or {}).get("research_ids") or [])
    return list(dict.fromkeys(str(item) for item in ids))[:6]


def _brand_id(state: RunState) -> str | None:
    return state.inputs.get("brand_id") or (state.latest("source_content") or {}).get("brand_id")


def _platforms(state: RunState) -> list[str]:
    return list(state.inputs.get("platforms") or PLATFORMS)


def _slim_research(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not result:
        return None
    slim = _pick(result, "summary", "audience_needs", "trends", "content_opportunities", "assumptions", "limitations")
    slim["findings"] = [
        _pick(item, "claim", "category", "verified", "source_refs") for item in (result.get("findings") or [])[:12]
    ]
    return slim


def _slim_strategy(result: dict[str, Any] | None) -> dict[str, Any] | None:
    return _pick(
        result, "strategy_summary", "audience_insights", "recommended_themes", "content_pillars",
        "campaign_objectives", "content_mix", "assumptions",
    ) or None


def _slim_draft(result: dict[str, Any] | None) -> dict[str, Any]:
    return _pick(result, "title", "versions", "alternative_hooks", "cta_recommendations", "factual_claims")


def _merge(state: RunState, bases: tuple[str, ...], field_name: str) -> list[Any]:
    merged: list[Any] = []
    for base in bases:
        for item in (state.envelope(base) or {}).get(field_name) or []:
            if item not in merged:
                merged.append(item)
    return merged


def _warnings(state: RunState, bases: tuple[str, ...]) -> list[str]:
    labelled: list[str] = []
    for base in bases:
        envelope = state.envelope(base) or {}
        for warning in envelope.get("warnings") or []:
            text = f"{envelope.get('agent_id', base)}: {warning}"
            if text not in labelled:
                labelled.append(text)
    return labelled


# Context steps --------------------------------------------------------------------


def brand_context(ctx: AgentContext, tools: ToolBox, state: RunState) -> dict[str, Any]:
    brand = tools.call("get_brand_profile", brand_id=state.inputs.get("brand_id"))
    return {
        "brand_id": brand["brand"]["id"],
        "brand_name": brand["brand"]["name"],
        "has_voice": brand.get("voice") is not None,
        "audiences": len(brand.get("audiences") or []),
        "content_pillars": [item["name"] for item in brand.get("content_pillars") or []],
        "goals": len(brand.get("goals") or []),
        "policies": len(brand.get("policies") or []),
    }


def research_context(ctx: AgentContext, tools: ToolBox, state: RunState) -> dict[str, Any]:
    ids = [str(item) for item in state.inputs.get("research_ids") or []]
    research = tools.call("get_research", research_ids=ids)
    result = {
        "research_ids": ids,
        "projects": [_pick(item, "id", "title", "status", "report_id") for item in research["projects"]],
        "source_count": len(research["sources"]),
    }
    if not ids:
        result["_warnings"] = ["No research was selected. The draft cannot be fact-checked against sources."]
    elif not research["sources"]:
        result["_warnings"] = ["The selected research has no stored sources. Claims cannot be confirmed."]
    return result


def source_content(ctx: AgentContext, tools: ToolBox, state: RunState) -> dict[str, Any]:
    project = tools.call("get_content_project", project_id=state.inputs.get("content_project_id"), approved_only=True)
    drafts = [draft for draft in project["drafts"] if (draft.get("body") or draft.get("hook"))]
    if not drafts:
        from app.services.agents.tools import ToolError

        raise ToolError("The approved content has no draft text to repurpose.")
    return {
        "project_id": project["project_id"],
        "brand_id": project["brand_id"],
        "title": project["title"],
        "topic": project["topic"],
        "objective": project["objective"],
        "status": project["status"],
        "drafts": [_pick(draft, "platform", "hook", "body", "cta", "hashtags") for draft in drafts],
    }


def analytics_context(ctx: AgentContext, tools: ToolBox, state: RunState) -> dict[str, Any]:
    days = int(state.inputs.get("days") or 30)
    data = tools.call("get_analytics", days=days, brand_id=state.inputs.get("brand_id"))
    result = {
        "days": days,
        "period": data.get("period"),
        "post_count": data.get("post_count"),
        "connected_accounts": data.get("connected_accounts"),
    }
    if not data.get("post_count"):
        result["_warnings"] = ["There are no measured posts in this period. The analysis will report insufficient data."]
    return result


# Agent inputs ---------------------------------------------------------------------


def research_input(state: RunState) -> dict[str, Any]:
    ids = [str(item) for item in state.inputs.get("research_ids") or []]
    return {
        "task": state.workflow.task,
        "brand_id": state.inputs.get("brand_id"),
        "research_ids": ids,
        "run_new_research": bool(state.inputs.get("run_new_research")) or not ids,
    }


def strategy_from_research(state: RunState) -> dict[str, Any]:
    return {
        "task": state.workflow.task,
        "brand_id": state.inputs.get("brand_id"),
        "research_ids": _research_ids(state),
        "research_findings": _slim_research(state.latest("research")),
    }


def strategy_from_analytics(state: RunState) -> dict[str, Any]:
    analytics = state.latest("analytics") or {}
    return {
        "task": state.workflow.task,
        "brand_id": state.inputs.get("brand_id"),
        "research_ids": _research_ids(state),
        "analytics_insights": _pick(
            analytics, "performance_summary", "patterns", "opportunities", "recommendations",
            "data_limitations", "measured_data",
        ),
    }


def plan_input(state: RunState) -> dict[str, Any]:
    source = state.latest("source_content")
    return {
        "task": state.workflow.task,
        "brand_id": _brand_id(state),
        "platforms": _platforms(state),
        "strategy": _slim_strategy(state.latest("strategy")),
        "research_findings": _slim_research(state.latest("research")),
        "research_ids": _research_ids(state),
        "source_content": _pick(source, "title", "topic", "objective", "drafts") if source else None,
        "idea_count": 5 if state.workflow.workflow_type == "content_research" else 3,
    }


def writer_input(state: RunState) -> dict[str, Any]:
    plan = state.latest("plan") or {}
    source = state.latest("source_content")
    data: dict[str, Any] = {
        "task": state.workflow.task,
        "brand_id": _brand_id(state),
        "platforms": _platforms(state),
        "plan": {"ideas": (plan.get("ideas") or [])[:3], "platform_adaptations": plan.get("platform_adaptations") or []},
        "research_ids": _research_ids(state),
        "source_content": _pick(source, "title", "topic", "objective", "drafts") if source else None,
        "revision_round": state.round,
    }
    if state.round > 0:
        data["previous_draft"] = _slim_draft(state.latest("writer", before_round=state.round))
        requests = review_issues(state, before_round=state.round)
        if state.feedback:
            requests.insert(0, f"Reviewer request: {state.feedback}")
        data["revision_requests"] = requests[:20]
    return data


def brand_review_input(state: RunState) -> dict[str, Any]:
    return {"brand_id": _brand_id(state), "draft": _slim_draft(state.latest("writer"))}


def fact_check_input(state: RunState) -> dict[str, Any]:
    return {"draft": _slim_draft(state.latest("writer")), "research_ids": _research_ids(state)}


def quality_input(state: RunState) -> dict[str, Any]:
    return {"draft": _slim_draft(state.latest("writer")), "task": state.workflow.task}


def analytics_input(state: RunState) -> dict[str, Any]:
    return {
        "task": state.workflow.task,
        "brand_id": state.inputs.get("brand_id"),
        "days": int(state.inputs.get("days") or 30),
    }


# Review gate ----------------------------------------------------------------------


def review_issues(state: RunState, *, before_round: int | None = None, settings: Settings | None = None) -> list[str]:
    """Problems the reviewers found that justify asking the writer for a revision."""
    reasons: list[str] = []
    brand = state.latest("brand_review", before_round=before_round) or {}
    for issue in brand.get("issues") or []:
        if issue.get("severity") == "high":
            reasons.append(f"Brand ({issue.get('category')}): {issue.get('explanation')} {issue.get('suggestion') or ''}".strip())
    facts = state.latest("fact_check", before_round=before_round) or {}
    for claim in facts.get("claims") or []:
        if claim.get("classification") in {"UNSUPPORTED", "CONTRADICTED"}:
            reasons.append(f"Fact check ({claim['classification']}): remove or correct the claim \"{claim.get('claim')}\".")
    quality = state.latest("quality", before_round=before_round) or {}
    score = quality.get("overall_score")
    improvements = list(quality.get("improvements") or [])[:5]
    if settings is None:
        # Building the writer's revision brief: pass on every editorial suggestion.
        reasons.extend(f"Quality: {item}" for item in improvements)
    elif score is not None and score < settings.agent_quality_revision_threshold:
        # Deciding whether to revise automatically: only a low score counts.
        reasons.extend(f"Quality score {score}/10: {item}" for item in improvements)
        if not improvements:
            reasons.append(
                f"Quality score {score}/10 is below the editorial threshold of {settings.agent_quality_revision_threshold}."
            )
    return reasons


def content_review_gate(state: RunState, settings: Settings) -> list[str]:
    return review_issues(state, settings=settings)


# Compile steps --------------------------------------------------------------------


def compile_research(ctx: AgentContext, tools: ToolBox, state: RunState) -> dict[str, Any]:
    research = state.latest("research") or {}
    strategy = state.latest("strategy") or {}
    plan = state.latest("plan") or {}
    bases = ("research", "strategy", "plan")
    return {
        "type": "content_research",
        "research_findings": _pick(research, "summary", "findings", "trends", "assumptions", "limitations", "research_ids", "sources_available"),
        "audience_insights": list(dict.fromkeys((research.get("audience_needs") or []) + (strategy.get("audience_insights") or []))),
        "strategic_recommendations": _pick(
            strategy, "strategy_summary", "recommended_themes", "content_pillars", "campaign_objectives",
            "content_mix", "supporting_evidence", "assumptions", "limitations",
        ),
        "content_opportunities": research.get("content_opportunities") or [],
        "content_ideas": plan.get("ideas") or [],
        "suggested_publishing_frequency": plan.get("suggested_publishing_frequency"),
        "platform_adaptations": plan.get("platform_adaptations") or [],
        "evidence": _merge(state, bases, "evidence"),
        "warnings": _warnings(state, bases),
        "human_review": HUMAN_REVIEW_NOTE,
    }


def _content_deliverable(state: RunState, kind: str, bases: tuple[str, ...]) -> dict[str, Any]:
    draft = state.latest("writer") or {}
    brand = state.latest("brand_review") or {}
    quality = state.latest("quality") or {}
    suggestions = list(dict.fromkeys((brand.get("suggested_improvements") or []) + (quality.get("improvements") or [])))
    return {
        "type": kind,
        "content_draft": _slim_draft(draft),
        "platform_versions": {item["platform"]: item for item in draft.get("versions") or []},
        "alternative_hooks": draft.get("alternative_hooks") or [],
        "cta_recommendations": draft.get("cta_recommendations") or [],
        "brand_review": brand,
        "quality_assessment": quality,
        "improvement_suggestions": suggestions,
        "revision_rounds": state.workflow.revision_count,
        "evidence": _merge(state, bases, "evidence"),
        "warnings": _warnings(state, bases),
        "human_review": HUMAN_REVIEW_NOTE,
    }


def compile_social_content(ctx: AgentContext, tools: ToolBox, state: RunState) -> dict[str, Any]:
    bases = ("research_context", "plan", "writer", "brand_review", "fact_check", "quality")
    deliverable = _content_deliverable(state, "social_content", bases)
    deliverable["fact_check"] = state.latest("fact_check") or {}
    deliverable["content_plan"] = _pick(state.latest("plan"), "ideas", "platform_adaptations")
    deliverable["research_ids"] = _research_ids(state)
    return deliverable


def compile_repurposing(ctx: AgentContext, tools: ToolBox, state: RunState) -> dict[str, Any]:
    bases = ("plan", "writer", "brand_review", "quality")
    deliverable = _content_deliverable(state, "content_repurposing", bases)
    versions = deliverable["platform_versions"]
    deliverable["facebook_adaptation"] = versions.get("facebook")
    deliverable["instagram_adaptation"] = versions.get("instagram")
    deliverable["source_content"] = _pick(state.latest("source_content"), "project_id", "title")
    return deliverable


def compile_performance(ctx: AgentContext, tools: ToolBox, state: RunState) -> dict[str, Any]:
    analytics = state.latest("analytics") or {}
    strategy = state.latest("strategy") or {}
    bases = ("analytics_context", "analytics", "strategy")
    return {
        "type": "performance_analysis",
        "performance_summary": analytics.get("performance_summary"),
        "measured_data": analytics.get("measured_data"),
        "content_patterns": analytics.get("patterns") or [],
        "improvement_opportunities": analytics.get("opportunities") or [],
        "recommendations": analytics.get("recommendations") or [],
        "suggested_experiments": analytics.get("experiments") or [],
        "data_limitations": analytics.get("data_limitations") or [],
        "unverified_numbers": analytics.get("unverified_numbers") or [],
        "strategic_recommendations": _pick(
            strategy, "strategy_summary", "recommended_themes", "content_mix", "supporting_evidence", "assumptions", "limitations"
        ),
        "metric_references": _merge(state, ("analytics",), "evidence"),
        "label": analytics.get("label"),
        "warnings": _warnings(state, bases),
        "human_review": HUMAN_REVIEW_NOTE + " Publishing schedules were not changed.",
    }


# Definitions ----------------------------------------------------------------------

WORKFLOWS: dict[str, WorkflowDef] = {}


def register_workflow(definition: WorkflowDef) -> WorkflowDef:
    keys = [step.key for step in definition.steps]
    if definition.key in WORKFLOWS or len(set(keys)) != len(keys) or not keys:
        raise WorkflowError(f"Invalid workflow definition: {definition.key}.")
    seen: set[str] = set()
    for step in definition.steps:
        if step.kind not in {"context", "agent", "compile"}:
            raise WorkflowError(f"Workflow {definition.key}: unknown step kind {step.kind}.")
        if any(dependency not in seen for dependency in step.depends_on):
            raise WorkflowError(f"Workflow {definition.key}: step {step.key} depends on a later or unknown step.")
        if step.kind == "agent":
            get_agent(step.agent_key)
            if step.build_input is None:
                raise WorkflowError(f"Workflow {definition.key}: agent step {step.key} needs an input builder.")
        elif step.run is None or step.agent_key != ORCHESTRATOR_KEY:
            raise WorkflowError(f"Workflow {definition.key}: step {step.key} must be run by the orchestrator.")
        seen.add(step.key)
    if any(key not in seen for key in definition.revision_steps):
        raise WorkflowError(f"Workflow {definition.key}: unknown revision step.")
    WORKFLOWS[definition.key] = definition
    return definition


def get_workflow(key: str) -> WorkflowDef:
    definition = WORKFLOWS.get(key)
    if definition is None:
        raise UnknownWorkflowError(f"Workflow '{key}' is not defined.")
    return definition


register_workflow(
    WorkflowDef(
        key="content_research",
        name="Complete content research",
        description="Research a topic, turn the findings into a strategy and get a list of content ideas.",
        deliverables=("Research findings", "Audience insights", "Strategic recommendations", "Content opportunities", "Suggested content ideas"),
        optional=("brand", "research", "platforms"),
        accept_mode="idea",
        steps=(
            StepDef("research", "agent", "Research the topic", "research", build_input=research_input),
            StepDef("strategy", "agent", "Develop the strategy", "marketing_strategist", ("research",), build_input=strategy_from_research),
            StepDef("plan", "agent", "Plan content ideas", "content_planner", ("strategy",), build_input=plan_input),
            StepDef("compile", "compile", "Compile the research deliverable", depends_on=("plan",), run=compile_research),
        ),
    )
)

register_workflow(
    WorkflowDef(
        key="social_content",
        name="Create high-quality social content",
        description="Plan and write a post for Facebook and Instagram, then review it for brand fit, facts and quality.",
        deliverables=("Content draft", "Platform-specific versions", "Brand review", "Fact-check report", "Quality assessment", "Improvement suggestions"),
        requires=("brand",),
        optional=("research", "platforms"),
        revision_steps=("writer", "brand_review", "fact_check", "quality", "compile"),
        review_gate=content_review_gate,
        accept_mode="draft",
        steps=(
            StepDef("brand_context", "context", "Retrieve brand context", run=brand_context),
            StepDef("research_context", "context", "Retrieve relevant research", depends_on=("brand_context",), run=research_context),
            StepDef("plan", "agent", "Plan the content", "content_planner", ("research_context",), build_input=plan_input),
            StepDef("writer", "agent", "Write the draft", "content_writer", ("plan",), build_input=writer_input),
            StepDef("brand_review", "agent", "Review brand consistency", "brand_guardian", ("writer",), "review", brand_review_input),
            StepDef("fact_check", "agent", "Check facts against sources", "fact_checker", ("writer",), "review", fact_check_input),
            StepDef("quality", "agent", "Assess content quality", "content_quality", ("writer",), "review", quality_input),
            StepDef("compile", "compile", "Compile results", depends_on=("brand_review", "fact_check", "quality"), run=compile_social_content),
        ),
    )
)

register_workflow(
    WorkflowDef(
        key="content_repurposing",
        name="Content repurposing",
        description="Adapt an approved piece of content for Facebook and Instagram with alternative hooks and calls to action.",
        deliverables=("Facebook adaptation", "Instagram adaptation", "Alternative hooks", "CTA recommendations", "Brand consistency results"),
        requires=("content_project",),
        optional=("brand", "platforms"),
        revision_steps=("writer", "brand_review", "quality", "compile"),
        review_gate=content_review_gate,
        accept_mode="draft",
        steps=(
            StepDef("source_content", "context", "Read the approved source content", run=source_content),
            StepDef("plan", "agent", "Plan the adaptations", "content_planner", ("source_content",), build_input=plan_input),
            StepDef("writer", "agent", "Write the adaptations", "content_writer", ("plan",), build_input=writer_input),
            StepDef("brand_review", "agent", "Review brand consistency", "brand_guardian", ("writer",), "review", brand_review_input),
            StepDef("quality", "agent", "Assess content quality", "content_quality", ("writer",), "review", quality_input),
            StepDef("compile", "compile", "Compile results", depends_on=("brand_review", "quality"), run=compile_repurposing),
        ),
    )
)

register_workflow(
    WorkflowDef(
        key="performance_analysis",
        name="Performance analysis",
        description="Interpret measured analytics and turn them into recommendations and experiments.",
        deliverables=("Performance summary", "Content patterns", "Improvement opportunities", "Suggested experiments", "Supporting metric references"),
        optional=("brand", "days"),
        steps=(
            StepDef("analytics_context", "context", "Retrieve analytics", run=analytics_context),
            StepDef("analytics", "agent", "Interpret performance", "analytics_strategist", ("analytics_context",), build_input=analytics_input),
            StepDef("strategy", "agent", "Recommend strategy changes", "marketing_strategist", ("analytics",), build_input=strategy_from_analytics),
            StepDef("compile", "compile", "Compile recommendations", depends_on=("strategy",), run=compile_performance),
        ),
    )
)


# Planning and input validation ----------------------------------------------------


def plan_steps(definition: WorkflowDef) -> list[dict[str, Any]]:
    """The planned execution, shown to the user before start and stored as step rows."""
    plan = []
    for order, step in enumerate(definition.steps, start=1):
        spec = get_agent(step.agent_key) if step.kind == "agent" else None
        plan.append(
            {
                "step_order": order,
                "step_key": step.key,
                "base_key": step.key,
                "kind": step.kind,
                "agent_key": step.agent_key,
                "agent_name": spec.name if spec else "Orchestrator",
                "label": step.label,
                "depends_on": list(step.depends_on),
                "parallel_group": step.parallel_group,
            }
        )
    return plan


def describe_workflow(definition: WorkflowDef) -> dict[str, Any]:
    return {
        "key": definition.key,
        "name": definition.name,
        "description": definition.description,
        "deliverables": list(definition.deliverables),
        "requires": list(definition.requires),
        "optional": list(definition.optional),
        "agents": definition.agent_keys,
        "supports_revision": bool(definition.revision_steps),
        "accept_mode": definition.accept_mode,
        "steps": plan_steps(definition),
    }


def validate_inputs(db: DBSession, workspace_id: UUID, definition: WorkflowDef, data: dict[str, Any]) -> dict[str, Any]:
    """Check every referenced record belongs to the workspace. Returns the stored ``input_data``."""
    brand_id = data.get("brand_id")
    if "brand" in definition.requires and not brand_id:
        raise WorkflowInputError("Select a brand for this workflow.")
    if brand_id:
        brand = db.query(Brand).filter(Brand.id == brand_id, Brand.workspace_id == workspace_id).first()
        if brand is None:
            raise WorkflowInputError("Brand not found in this workspace.", not_found=True)
        if brand.status != "ACTIVE":
            raise WorkflowInputError("Archived brands cannot be used in a workflow.")
    research_ids = list(dict.fromkeys(data.get("research_ids") or []))
    if research_ids:
        found = (
            db.query(ResearchProject.id)
            .filter(ResearchProject.workspace_id == workspace_id, ResearchProject.id.in_(research_ids))
            .count()
        )
        if found != len(research_ids):
            raise WorkflowInputError("Research project not found in this workspace.", not_found=True)
    project_id = data.get("content_project_id")
    if "content_project" in definition.requires:
        if not project_id:
            raise WorkflowInputError("Select an approved content item to repurpose.")
        project = (
            db.query(ContentProject)
            .filter(ContentProject.id == project_id, ContentProject.workspace_id == workspace_id)
            .first()
        )
        if project is None:
            raise WorkflowInputError("Content item not found in this workspace.", not_found=True)
        if project.status != "approved":
            raise WorkflowInputError("Only approved content can be repurposed.")
    platforms = [str(item) for item in (data.get("platforms") or PLATFORMS)]
    if not platforms or any(item not in PLATFORMS for item in platforms):
        raise WorkflowInputError("Platforms must be Facebook and/or Instagram.")
    return {
        "brand_id": str(brand_id) if brand_id else None,
        "research_ids": [str(item) for item in research_ids],
        "content_project_id": str(project_id) if project_id and "content_project" in definition.requires else None,
        "platforms": list(dict.fromkeys(platforms)),
        "days": int(data.get("days") or 30),
        "run_new_research": bool(data.get("run_new_research")),
    }
