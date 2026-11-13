"""Phase 10 automation API.

Routes live under ``/workspaces/{workspace_id}/automations`` and
``/workspaces/{workspace_id}/automation-executions``. Members can read
automations, executions and the catalogue; only Owners and Admins can create,
edit, enable, pause, resume, archive, delete, duplicate, dry-run or retry.
Every id from the browser is checked against the workspace; inaccessible ids
return 404.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import get_current_user, require_workspace_admin, require_workspace_member
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Automation, AutomationExecution, Brand, User, WorkspaceMembership
from app.schemas.automation import (
    AutomationCreate,
    AutomationDetailRead,
    AutomationRead,
    AutomationUpdate,
    CatalogRead,
    DryRunDefinitionRequest,
    DryRunRead,
    DryRunRequest,
    ExecutionRead,
    ValidationRead,
)
from app.services.automation import actions as A
from app.services.automation import engine
from app.services.automation import service as S
from app.services.automation.registry import TRIGGERS, list_triggers

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["automations"])

STATUS_PATTERN = "^(draft|enabled|paused|archived)$"
EXECUTION_STATUS_PATTERN = "^(pending|running|succeeded|failed|cancelled)$"


# Serialization -----------------------------------------------------------------


def execution_read(db: DBSession, execution: AutomationExecution, *, include_steps: bool = True, automation: Automation | None = None) -> ExecutionRead:
    automation = automation or db.get(Automation, execution.automation_id)
    return ExecutionRead(
        id=execution.id,
        automation_id=execution.automation_id,
        automation_name=automation.name if automation else None,
        workspace_id=execution.workspace_id,
        trigger_event_id=execution.trigger_event_id,
        trigger_type=execution.trigger_type,
        status=execution.status,
        retry_count=execution.retry_count,
        max_retries=execution.max_retries,
        next_attempt_at=execution.next_attempt_at,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        error_message=execution.error_message,
        chain_depth=execution.chain_depth,
        created_at=execution.created_at,
        can_retry=execution.status == "failed" and automation is not None and automation.status == "enabled",
        execution_context=dict(execution.execution_context or {}) if include_steps else {},
        steps=[
            {
                "id": step.id,
                "action_type": step.action_type,
                "execution_order": step.execution_order,
                "status": step.status,
                "started_at": step.started_at,
                "completed_at": step.completed_at,
                "result_summary": step.result_summary,
                "error_message": step.error_message,
            }
            for step in sorted(execution.steps, key=lambda item: item.execution_order)
        ]
        if include_steps
        else [],
    )


def _last_execution(db: DBSession, automation: Automation) -> AutomationExecution | None:
    return (
        db.query(AutomationExecution)
        .filter(AutomationExecution.automation_id == automation.id)
        .order_by(AutomationExecution.created_at.desc())
        .first()
    )


def automation_read(db: DBSession, automation: Automation, *, detail: bool = False) -> dict[str, Any]:
    brand = db.get(Brand, automation.brand_id) if automation.brand_id else None
    creator = db.get(User, automation.created_by) if automation.created_by else None
    last = _last_execution(db, automation)
    issues = S.automation_issues(db, automation)
    trigger = TRIGGERS.get(automation.trigger_type)
    data: dict[str, Any] = {
        "id": automation.id,
        "workspace_id": automation.workspace_id,
        "brand_id": automation.brand_id,
        "brand_name": brand.name if brand else None,
        "name": automation.name,
        "description": automation.description,
        "status": automation.status,
        "trigger_type": automation.trigger_type,
        "trigger_label": trigger.label if trigger else automation.trigger_type,
        "trigger_configuration": dict(automation.trigger_configuration or {}),
        "conditions": dict(automation.conditions or {"logic": "and", "rules": []}),
        "max_executions": automation.max_executions,
        "cooldown_seconds": automation.cooldown_seconds,
        "execution_count": automation.execution_count,
        "success_count": automation.success_count,
        "failure_count": automation.failure_count,
        "last_executed_at": automation.last_executed_at,
        "last_execution": execution_read(db, last, include_steps=False, automation=automation) if last else None,
        "created_by": automation.created_by,
        "created_by_name": creator.full_name if creator else None,
        "updated_by": automation.updated_by,
        "created_at": automation.created_at,
        "updated_at": automation.updated_at,
        "enabled_at": automation.enabled_at,
        "paused_at": automation.paused_at,
        "archived_at": automation.archived_at,
        "actions": [
            {
                "id": item.id,
                "action_type": item.action_type,
                "label": A.ACTIONS[item.action_type].label if item.action_type in A.ACTIONS else item.action_type,
                "action_configuration": dict(item.action_configuration or {}),
                "execution_order": item.execution_order,
            }
            for item in sorted(automation.actions, key=lambda item: item.execution_order)
        ],
        "issues": issues,
        "can_enable": automation.status in {"draft", "paused"} and bool(automation.actions) and not issues,
    }
    if detail:
        recent = (
            db.query(AutomationExecution)
            .filter(AutomationExecution.automation_id == automation.id)
            .order_by(AutomationExecution.created_at.desc())
            .limit(20)
            .all()
        )
        data["recent_executions"] = [execution_read(db, item, automation=automation) for item in recent]
        data["last_dry_run"] = automation.last_dry_run
        data["last_dry_run_at"] = automation.last_dry_run_at
    return data


def _get_automation(db: DBSession, workspace_id: UUID, automation_id: UUID) -> Automation:
    automation = db.get(Automation, automation_id)
    if automation is None or automation.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Automation not found.")
    return automation


def _raise(exc: S.AutomationError) -> None:
    detail: Any = exc.errors if len(exc.errors) > 1 or exc.errors[0] != str(exc) else str(exc)
    raise HTTPException(status_code=exc.status_code, detail=detail)


def _limits() -> dict[str, Any]:
    settings = get_settings()
    return {
        "max_automations_per_workspace": settings.automation_max_per_workspace,
        "max_actions": settings.automation_max_actions,
        "max_conditions": settings.automation_max_conditions,
        "max_condition_depth": settings.automation_max_condition_depth,
        "max_executions_per_hour": settings.automation_max_executions_per_hour,
        "workspace_max_executions_per_day": settings.automation_workspace_max_executions_per_day,
        "max_chain_depth": settings.automation_max_chain_depth,
        "max_retries": settings.automation_max_retries,
        "execution_timeout_seconds": settings.automation_execution_timeout_seconds,
        "max_concurrent_executions": settings.automation_max_concurrent_executions,
        "enabled": settings.automation_enabled,
    }


# Catalogue and validation ------------------------------------------------------


@router.get("/automations/catalog", response_model=CatalogRead)
def get_catalog(
    workspace_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
) -> dict[str, Any]:
    return {"triggers": list_triggers(), "actions": A.list_actions(), "limits": _limits()}


@router.post("/automations/validate", response_model=ValidationRead)
def validate_automation(
    workspace_id: UUID,
    payload: AutomationCreate,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    normalized = S.validate_definition(
        db,
        workspace_id=workspace_id,
        trigger_type=payload.trigger_type,
        trigger_configuration=payload.trigger_configuration,
        conditions=payload.conditions,
        actions=[item.model_dump() for item in payload.actions],
        brand_id=payload.brand_id,
    )
    return {"valid": normalized.valid, "errors": normalized.errors, "warnings": normalized.warnings}


@router.post("/automations/dry-run", response_model=DryRunRead)
def dry_run_definition(
    workspace_id: UUID,
    payload: DryRunDefinitionRequest,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    definition = payload.automation
    return S.dry_run(
        db,
        workspace_id=workspace_id,
        actor=membership,
        name=definition.name,
        trigger_type=definition.trigger_type,
        trigger_configuration=definition.trigger_configuration,
        conditions=definition.conditions,
        actions=[item.model_dump() for item in definition.actions],
        brand_id=definition.brand_id,
        payload_source=payload.payload_source,
        payload_overrides=payload.payload_overrides,
    )


# Executions (declared before /automations/{automation_id} to avoid path clashes) -----


@router.get("/automation-executions", response_model=list[ExecutionRead])
def list_executions(
    workspace_id: UUID,
    automation_id: UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status", pattern=EXECUTION_STATUS_PATTERN),
    limit: int = Query(default=50, ge=1, le=200),
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> list[ExecutionRead]:
    query = db.query(AutomationExecution).filter(AutomationExecution.workspace_id == workspace_id)
    if automation_id is not None:
        query = query.filter(AutomationExecution.automation_id == automation_id)
    if status_filter:
        query = query.filter(AutomationExecution.status == status_filter)
    rows = query.order_by(AutomationExecution.created_at.desc()).limit(limit).all()
    return [execution_read(db, row, include_steps=False) for row in rows]


@router.get("/automation-executions/{execution_id}", response_model=ExecutionRead)
def get_execution(
    workspace_id: UUID,
    execution_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> ExecutionRead:
    execution = db.get(AutomationExecution, execution_id)
    if execution is None or execution.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Execution not found.")
    return execution_read(db, execution)


@router.post("/automation-executions/{execution_id}/retry", response_model=ExecutionRead)
def retry_execution(
    workspace_id: UUID,
    execution_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ExecutionRead:
    execution = db.get(AutomationExecution, execution_id)
    if execution is None or execution.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Execution not found.")
    try:
        engine.retry_execution(db, execution, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return execution_read(db, execution)


# Automations -------------------------------------------------------------------


@router.get("/automations", response_model=list[AutomationRead])
def list_automations(
    workspace_id: UUID,
    status_filter: str | None = Query(default=None, alias="status", pattern=STATUS_PATTERN),
    trigger_type: str | None = Query(default=None, max_length=64),
    include_archived: bool = Query(default=False),
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> list[dict[str, Any]]:
    query = db.query(Automation).filter(Automation.workspace_id == workspace_id)
    if status_filter:
        query = query.filter(Automation.status == status_filter)
    elif not include_archived:
        query = query.filter(Automation.status != "archived")
    if trigger_type:
        query = query.filter(Automation.trigger_type == trigger_type)
    rows = query.order_by(Automation.updated_at.desc()).all()
    return [automation_read(db, row) for row in rows]


@router.post("/automations", response_model=AutomationRead, status_code=status.HTTP_201_CREATED)
def create_automation(
    workspace_id: UUID,
    payload: AutomationCreate,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        automation = S.create_automation(db, workspace_id=workspace_id, user_id=current_user.id, data=payload.model_dump())
    except S.AutomationError as exc:
        _raise(exc)
    return automation_read(db, automation)


@router.get("/automations/{automation_id}", response_model=AutomationDetailRead)
def get_automation(
    workspace_id: UUID,
    automation_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    return automation_read(db, _get_automation(db, workspace_id, automation_id), detail=True)


@router.patch("/automations/{automation_id}", response_model=AutomationDetailRead)
def update_automation(
    workspace_id: UUID,
    automation_id: UUID,
    payload: AutomationUpdate,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    automation = _get_automation(db, workspace_id, automation_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field is required.")
    try:
        S.update_automation(db, automation, user_id=current_user.id, changes=changes)
    except S.AutomationError as exc:
        _raise(exc)
    return automation_read(db, automation, detail=True)


@router.delete("/automations/{automation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_automation(
    workspace_id: UUID,
    automation_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    automation = _get_automation(db, workspace_id, automation_id)
    try:
        S.delete_automation(db, automation, user_id=current_user.id)
    except S.AutomationError as exc:
        _raise(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _transition(db: DBSession, workspace_id: UUID, automation_id: UUID, membership: WorkspaceMembership, action: str) -> dict[str, Any]:
    automation = _get_automation(db, workspace_id, automation_id)
    try:
        if action == "enable":
            S.enable_automation(db, automation, membership=membership)
        elif action == "pause":
            S.pause_automation(db, automation, user_id=membership.user_id)
        elif action == "resume":
            S.resume_automation(db, automation, membership=membership)
        elif action == "archive":
            S.archive_automation(db, automation, user_id=membership.user_id)
    except S.AutomationError as exc:
        _raise(exc)
    return automation_read(db, automation, detail=True)


@router.post("/automations/{automation_id}/enable", response_model=AutomationDetailRead)
def enable_automation(
    workspace_id: UUID,
    automation_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    return _transition(db, workspace_id, automation_id, membership, "enable")


@router.post("/automations/{automation_id}/pause", response_model=AutomationDetailRead)
def pause_automation(
    workspace_id: UUID,
    automation_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    return _transition(db, workspace_id, automation_id, membership, "pause")


@router.post("/automations/{automation_id}/resume", response_model=AutomationDetailRead)
def resume_automation(
    workspace_id: UUID,
    automation_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    return _transition(db, workspace_id, automation_id, membership, "resume")


@router.post("/automations/{automation_id}/archive", response_model=AutomationDetailRead)
def archive_automation(
    workspace_id: UUID,
    automation_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    return _transition(db, workspace_id, automation_id, membership, "archive")


@router.post("/automations/{automation_id}/duplicate", response_model=AutomationRead, status_code=status.HTTP_201_CREATED)
def duplicate_automation(
    workspace_id: UUID,
    automation_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    automation = _get_automation(db, workspace_id, automation_id)
    try:
        copy = S.duplicate_automation(db, automation, user_id=membership.user_id)
    except S.AutomationError as exc:
        _raise(exc)
    return automation_read(db, copy)


@router.post("/automations/{automation_id}/dry-run", response_model=DryRunRead)
def dry_run_automation(
    workspace_id: UUID,
    automation_id: UUID,
    payload: DryRunRequest | None = None,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    automation = _get_automation(db, workspace_id, automation_id)
    payload = payload or DryRunRequest()
    actor = engine.automation_actor(db, automation) if automation.status != "draft" else membership
    return S.dry_run(
        db,
        workspace_id=workspace_id,
        actor=actor or membership,
        name=automation.name,
        trigger_type=automation.trigger_type,
        trigger_configuration=automation.trigger_configuration,
        conditions=automation.conditions,
        actions=[{"action_type": item.action_type, "configuration": item.action_configuration} for item in automation.actions],
        brand_id=automation.brand_id,
        payload_source=payload.payload_source,
        payload_overrides=payload.payload_overrides,
        automation=automation,
    )


@router.get("/automations/{automation_id}/dry-run", response_model=DryRunRead | None)
def get_last_dry_run(
    workspace_id: UUID,
    automation_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any] | None:
    automation = _get_automation(db, workspace_id, automation_id)
    return automation.last_dry_run


@router.get("/automations/{automation_id}/executions", response_model=list[ExecutionRead])
def list_automation_executions(
    workspace_id: UUID,
    automation_id: UUID,
    status_filter: str | None = Query(default=None, alias="status", pattern=EXECUTION_STATUS_PATTERN),
    limit: int = Query(default=50, ge=1, le=200),
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> list[ExecutionRead]:
    automation = _get_automation(db, workspace_id, automation_id)
    query = db.query(AutomationExecution).filter(AutomationExecution.automation_id == automation.id)
    if status_filter:
        query = query.filter(AutomationExecution.status == status_filter)
    rows = query.order_by(AutomationExecution.created_at.desc()).limit(limit).all()
    return [execution_read(db, row, automation=automation) for row in rows]
