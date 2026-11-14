"""Phase 11 multi-agent API.

Routes live under ``/workspaces/{workspace_id}/agents`` and
``/workspaces/{workspace_id}/agent-workflows``. Every workspace member can read
the registry, start a predefined workflow and review its output; switching an
agent on or off needs an Owner or Admin; cancelling needs the person who
started the workflow or an Owner/Admin. Every id from the browser is checked
against the workspace; inaccessible ids return 404.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import get_current_user, require_workspace_admin, require_workspace_member
from app.core.config import get_settings
from app.db.session import get_db
from app.models import AgentExecution, AgentWorkflow, Brand, User, WorkspaceMembership
from app.schemas.agents import (
    AcceptRead,
    AcceptRequest,
    AgentRead,
    AgentUpdateRequest,
    CatalogRead,
    ExecutionRead,
    PlanRead,
    RejectRequest,
    ReviseRequest,
    StatsRead,
    WorkflowDetailRead,
    WorkflowListRead,
    WorkflowRead,
    WorkflowStartRequest,
)
from app.services.agents import orchestrator as O
from app.services.agents import service as S
from app.services.agents import workflows as W
from app.services.agents.registry import (
    ORCHESTRATOR_KEY,
    AGENTS,
    AgentDisabledError,
    UnknownAgentError,
    describe_agent,
    disabled_agent_keys,
    get_agent,
    list_agents,
    set_agent_enabled,
)
from app.services.agents.tools import ToolError
from app.services.audit import record_audit
from app.services.groq import GroqService
from app.services.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["ai agents"])

STATUS_PATTERN = "^(pending|running|succeeded|failed|cancelled)$"


# Serialization --------------------------------------------------------------------


def _agent_name(key: str) -> str:
    return AGENTS[key].name if key in AGENTS else "Orchestrator" if key == ORCHESTRATOR_KEY else key


def execution_read(execution: AgentExecution, *, detail: bool) -> dict[str, Any]:
    envelope = execution.output_data or {}
    return {
        "id": execution.id,
        "step_key": execution.step_key,
        "agent_key": execution.agent_key,
        "agent_version": execution.agent_version,
        "attempt_number": execution.attempt_number,
        "status": execution.status,
        "model_name": execution.model_name,
        "token_usage": execution.token_usage,
        "execution_duration_ms": execution.execution_duration_ms,
        "error_message": execution.error_message,
        "started_at": execution.started_at,
        "completed_at": execution.completed_at,
        "warnings": list(envelope.get("warnings") or []),
        "evidence": list(envelope.get("evidence") or []) if detail else [],
        "result": (envelope.get("result") or {}) if detail else None,
        "input_data": dict(execution.input_data or {}) if detail else None,
    }


def workflow_read(db: DBSession, workflow: AgentWorkflow, membership: WorkspaceMembership, *, detail: bool = False) -> dict[str, Any]:
    settings = get_settings()
    definition = W.WORKFLOWS.get(workflow.workflow_type)
    brand = db.get(Brand, workflow.brand_id) if workflow.brand_id else None
    creator = db.get(User, workflow.created_by) if workflow.created_by else None
    steps = sorted(workflow.steps, key=lambda item: item.step_order)
    finished = workflow.status == "succeeded" and bool(workflow.final_output)
    supports_revision = bool(definition and definition.revision_steps)
    accept_mode = definition.accept_mode if definition else None
    is_manager = membership.role in {"OWNER", "ADMIN"} or workflow.created_by == membership.user_id
    data: dict[str, Any] = {
        "id": workflow.id,
        "workspace_id": workflow.workspace_id,
        "brand_id": workflow.brand_id,
        "brand_name": brand.name if brand else None,
        "workflow_type": workflow.workflow_type,
        "workflow_name": definition.name if definition else workflow.workflow_type,
        "name": workflow.name,
        "task": workflow.task,
        "status": workflow.status,
        "error_message": workflow.error_message,
        "cancel_requested": workflow.cancel_requested,
        "agent_call_count": workflow.agent_call_count,
        "revision_count": workflow.revision_count,
        "total_tokens": workflow.total_tokens,
        "prompt_tokens": workflow.prompt_tokens,
        "completion_tokens": workflow.completion_tokens,
        "review_status": workflow.review_status,
        "review_note": workflow.review_note,
        "accepted_project_id": workflow.accepted_project_id,
        "created_by": workflow.created_by,
        "created_by_name": creator.full_name if creator else None,
        "created_at": workflow.created_at,
        "started_at": workflow.started_at,
        "completed_at": workflow.completed_at,
        "next_attempt_at": workflow.next_attempt_at,
        "steps_total": len(steps),
        "steps_done": sum(1 for step in steps if step.status == "succeeded"),
        "can_cancel": workflow.status in {"pending", "running"} and not workflow.cancel_requested and is_manager,
        "can_accept": finished
        and accept_mode is not None
        and (workflow.review_status == "pending" or (accept_mode == "idea" and workflow.review_status == "accepted")),
        "can_revise": finished
        and supports_revision
        and workflow.review_status == "pending"
        and workflow.revision_count < settings.agent_max_revisions,
        "can_reject": finished and workflow.review_status == "pending",
        "supports_revision": supports_revision,
        "accept_mode": accept_mode,
    }
    if detail:
        executions = {execution.id: execution for execution in workflow.executions}
        data["input_data"] = dict(workflow.input_data or {})
        data["agents"] = definition.agent_keys if definition else []
        data["final_output"] = workflow.final_output
        data["steps"] = [
            {
                "id": step.id,
                "step_order": step.step_order,
                "step_key": step.step_key,
                "base_key": step.base_key,
                "revision_round": step.revision_round,
                "kind": step.kind,
                "agent_key": step.agent_key,
                "agent_name": _agent_name(step.agent_key),
                "label": step.label,
                "depends_on": list((step.dependency_configuration or {}).get("depends_on") or []),
                "parallel_group": (step.dependency_configuration or {}).get("parallel_group"),
                "status": step.status,
                "attempt_count": step.attempt_count,
                "error_message": step.error_message,
                "execution": execution_read(executions[step.execution_id], detail=True)
                if step.execution_id in executions
                else None,
            }
            for step in steps
        ]
        data["messages"] = [
            {
                "sender": message.sender_agent,
                "receiver": message.receiver_agent,
                "type": message.message_type,
                "payload": message.structured_payload,
                "created_at": message.created_at,
            }
            for message in workflow.messages[-200:]
        ]
    return data


def _definition_read(definition: W.WorkflowDef, disabled: set[str]) -> dict[str, Any]:
    data = W.describe_workflow(definition)
    data["disabled_agents"] = [key for key in definition.agent_keys if key in disabled]
    return data


def _workflow(db: DBSession, workspace_id: UUID, workflow_id: UUID) -> AgentWorkflow:
    workflow = (
        db.query(AgentWorkflow)
        .filter(AgentWorkflow.id == workflow_id, AgentWorkflow.workspace_id == workspace_id)
        .first()
    )
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")
    return workflow


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, W.UnknownWorkflowError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, W.WorkflowInputError):
        code = status.HTTP_404_NOT_FOUND if exc.not_found else status.HTTP_422_UNPROCESSABLE_ENTITY
        return HTTPException(status_code=code, detail=str(exc))
    if isinstance(exc, O.WorkflowLimitError):
        return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    if isinstance(exc, (O.WorkflowStateError, AgentDisabledError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, ToolError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


_HANDLED = (W.WorkflowError, AgentDisabledError, ToolError)


# Agent registry -------------------------------------------------------------------


@router.get("/agents", response_model=list[AgentRead])
def list_registered_agents(
    workspace_id: UUID,
    _membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> list[dict[str, Any]]:
    disabled = disabled_agent_keys(db, workspace_id)
    return [describe_agent(spec, enabled=spec.key not in disabled) for spec in list_agents()]


@router.get("/agents/{agent_key}", response_model=AgentRead)
def get_registered_agent(
    workspace_id: UUID,
    agent_key: str,
    _membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        spec = get_agent(agent_key)
    except UnknownAgentError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.") from exc
    return describe_agent(spec, enabled=spec.key not in disabled_agent_keys(db, workspace_id))


@router.patch("/agents/{agent_key}", response_model=AgentRead)
def update_registered_agent(
    workspace_id: UUID,
    agent_key: str,
    payload: AgentUpdateRequest,
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_admin),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        spec = get_agent(agent_key)
    except UnknownAgentError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.") from exc
    set_agent_enabled(db, workspace_id, agent_key, enabled=payload.enabled, user_id=current_user.id)
    record_audit(
        db,
        action="agent.enabled" if payload.enabled else "agent.disabled",
        resource_type="agent",
        actor_user_id=current_user.id,
        workspace_id=workspace_id,
        resource_id=agent_key,
    )
    db.commit()
    return describe_agent(spec, enabled=payload.enabled)


# Workflow catalogue and planning --------------------------------------------------


@router.get("/agent-workflows/catalog", response_model=CatalogRead)
def workflow_catalog(
    workspace_id: UUID,
    _membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    settings = get_settings()
    disabled = disabled_agent_keys(db, workspace_id)
    groq = GroqService(db, workspace_id).configuration_status()
    return {
        "workflows": [_definition_read(definition, disabled) for definition in W.WORKFLOWS.values()],
        "agents": [describe_agent(spec, enabled=spec.key not in disabled) for spec in list_agents()],
        "limits": S.limits(settings),
        "groq": {
            "provider": "groq",
            "enabled": groq["enabled"],
            "configured": groq["configured"],
            "source": groq["source"],
            # Model ids come from configuration, never from a hardcoded list.
            "model_name": settings.agent_groq_model.strip() or groq["model_name"],
            "agent_model_override": bool(settings.agent_groq_model.strip()),
            "search_provider_configured": bool(
                settings.research_search_provider.strip() and settings.research_search_api_key.strip()
            ),
        },
    }


def _plan(db: DBSession, workspace_id: UUID, payload: WorkflowStartRequest) -> dict[str, Any]:
    settings = get_settings()
    definition = W.get_workflow(payload.workflow_type)
    disabled = disabled_agent_keys(db, workspace_id)
    input_data = W.validate_inputs(db, workspace_id, definition, payload.model_dump(exclude={"workflow_type", "task", "name"}))
    agent_steps = sum(1 for step in definition.steps if step.kind == "agent")
    notes = ["Agents produce drafts and recommendations only. Nothing is approved, scheduled or published."]
    if definition.revision_steps:
        notes.append(
            f"If reviewers find serious issues, the writer is asked for up to {settings.agent_max_auto_revisions} automatic revision(s)."
        )
    if definition.key == "content_research" and (payload.run_new_research or not payload.research_ids):
        if settings.research_search_provider.strip() and settings.research_search_api_key.strip():
            notes.append("A new research project will be created with the configured search provider.")
        else:
            notes.append("No search provider is configured, so findings will be labelled as unverified assumptions.")
    if definition.key == "social_content" and not payload.research_ids:
        notes.append("No research is selected, so factual claims cannot be confirmed against sources.")
    missing = [AGENTS[key].name for key in definition.agent_keys if key in disabled]
    if missing:
        notes.append(f"Disabled in this workspace: {', '.join(missing)}. The workflow cannot start until they are enabled.")
    return {
        "workflow": _definition_read(definition, disabled),
        "input_data": input_data,
        "estimated_agent_calls": agent_steps,
        "notes": notes,
    }


@router.post("/agent-workflows/plan", response_model=PlanRead)
def plan_workflow(
    workspace_id: UUID,
    payload: WorkflowStartRequest,
    _membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    """Validate the inputs and show the planned execution. Starts nothing."""
    try:
        return _plan(db, workspace_id, payload)
    except _HANDLED as exc:
        raise _http_error(exc) from exc


# Workflows ------------------------------------------------------------------------


@router.post("/agent-workflows", response_model=WorkflowDetailRead, status_code=status.HTTP_201_CREATED)
def start_workflow(
    workspace_id: UUID,
    payload: WorkflowStartRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    enforce_rate_limit(
        request, action="agent-workflow-start", identity=str(current_user.id), limit=10, window_seconds=60, category="AI workflow"
    )
    try:
        workflow = O.create_workflow(
            db,
            workspace_id=workspace_id,
            user=current_user,
            workflow_type=payload.workflow_type,
            task=payload.task,
            name=payload.name,
            data=payload.model_dump(exclude={"workflow_type", "task", "name"}),
        )
    except _HANDLED as exc:
        db.rollback()
        raise _http_error(exc) from exc
    return workflow_read(db, workflow, membership, detail=True)


@router.get("/agent-workflows", response_model=WorkflowListRead)
def list_workflows(
    workspace_id: UUID,
    status_filter: str | None = Query(default=None, alias="status", pattern=STATUS_PATTERN),
    workflow_type: str | None = Query(default=None, max_length=64),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    query = db.query(AgentWorkflow).filter(AgentWorkflow.workspace_id == workspace_id)
    if status_filter:
        query = query.filter(AgentWorkflow.status == status_filter)
    if workflow_type:
        query = query.filter(AgentWorkflow.workflow_type == workflow_type)
    total = query.count()
    rows = query.order_by(AgentWorkflow.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [workflow_read(db, row, membership) for row in rows], "total": total, "offset": offset, "limit": limit}


@router.get("/agent-workflows/stats", response_model=StatsRead)
def workflow_stats(
    workspace_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    stats = S.workspace_stats(db, workspace_id)
    recent = (
        db.query(AgentWorkflow)
        .filter(AgentWorkflow.workspace_id == workspace_id)
        .order_by(AgentWorkflow.created_at.desc())
        .limit(5)
        .all()
    )
    stats["recent"] = [workflow_read(db, row, membership) for row in recent]
    return stats


@router.get("/agent-workflows/{workflow_id}", response_model=WorkflowDetailRead)
def get_workflow(
    workspace_id: UUID,
    workflow_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    return workflow_read(db, _workflow(db, workspace_id, workflow_id), membership, detail=True)


@router.get("/agent-workflows/{workflow_id}/progress", response_model=WorkflowRead)
def get_workflow_progress(
    workspace_id: UUID,
    workflow_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    return workflow_read(db, _workflow(db, workspace_id, workflow_id), membership)


@router.get("/agent-workflows/{workflow_id}/output")
def get_workflow_output(
    workspace_id: UUID,
    workflow_id: UUID,
    _membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    workflow = _workflow(db, workspace_id, workflow_id)
    return {
        "workflow_id": workflow.id,
        "status": workflow.status,
        "review_status": workflow.review_status,
        "final_output": workflow.final_output,
    }


@router.get("/agent-workflows/{workflow_id}/executions/{execution_id}", response_model=ExecutionRead)
def get_agent_execution(
    workspace_id: UUID,
    workflow_id: UUID,
    execution_id: UUID,
    _membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    workflow = _workflow(db, workspace_id, workflow_id)
    execution = (
        db.query(AgentExecution)
        .filter(
            AgentExecution.id == execution_id,
            AgentExecution.workflow_id == workflow.id,
            AgentExecution.workspace_id == workspace_id,
        )
        .first()
    )
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent output not found.")
    return execution_read(execution, detail=True)


@router.post("/agent-workflows/{workflow_id}/cancel", response_model=WorkflowDetailRead)
def cancel_workflow(
    workspace_id: UUID,
    workflow_id: UUID,
    current_user: User = Depends(get_current_user),
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    workflow = _workflow(db, workspace_id, workflow_id)
    if membership.role not in {"OWNER", "ADMIN"} and workflow.created_by != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the person who started this workflow or an admin can cancel it.")
    try:
        workflow = O.request_cancel(db, workflow, user=current_user)
    except _HANDLED as exc:
        raise _http_error(exc) from exc
    return workflow_read(db, workflow, membership, detail=True)


# Human review ---------------------------------------------------------------------


@router.post("/agent-workflows/{workflow_id}/accept", response_model=AcceptRead)
def accept_workflow_output(
    workspace_id: UUID,
    workflow_id: UUID,
    payload: AcceptRequest,
    current_user: User = Depends(get_current_user),
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    """Save the reviewed draft as a draft content project. It still needs approval before publishing."""
    workflow = _workflow(db, workspace_id, workflow_id)
    try:
        created = S.accept_output(db, workflow, user=current_user, membership=membership, idea_index=payload.idea_index)
    except _HANDLED as exc:
        db.rollback()
        raise _http_error(exc) from exc
    return {**created, "workflow": workflow_read(db, workflow, membership)}


@router.post("/agent-workflows/{workflow_id}/revise", response_model=WorkflowDetailRead)
def revise_workflow_output(
    workspace_id: UUID,
    workflow_id: UUID,
    payload: ReviseRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    enforce_rate_limit(
        request, action="agent-workflow-revise", identity=str(current_user.id), limit=10, window_seconds=60, category="AI workflow"
    )
    workflow = _workflow(db, workspace_id, workflow_id)
    try:
        workflow = S.request_revision(db, workflow, user=current_user, feedback=payload.feedback)
    except _HANDLED as exc:
        db.rollback()
        raise _http_error(exc) from exc
    return workflow_read(db, workflow, membership, detail=True)


@router.post("/agent-workflows/{workflow_id}/reject", response_model=WorkflowDetailRead)
def reject_workflow_output(
    workspace_id: UUID,
    workflow_id: UUID,
    payload: RejectRequest,
    current_user: User = Depends(get_current_user),
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    workflow = _workflow(db, workspace_id, workflow_id)
    try:
        workflow = S.reject_output(db, workflow, user=current_user, reason=payload.reason)
    except _HANDLED as exc:
        db.rollback()
        raise _http_error(exc) from exc
    return workflow_read(db, workflow, membership, detail=True)
