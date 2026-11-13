"""Automation management: validation, lifecycle, duplication and dry runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.models import (
    Automation,
    AutomationAction,
    AutomationEvent,
    AutomationExecution,
    Brand,
    WorkspaceMembership,
)
from app.services.audit import record_audit
from app.services.automation import actions as A
from app.services.automation.conditions import ConditionError, evaluate_conditions, validate_conditions
from app.services.automation.engine import automation_actor
from app.services.automation.registry import (
    TriggerError,
    TriggerSpec,
    get_trigger,
    normalize_payload,
    payload_errors,
    validate_trigger_configuration,
)

ADMIN_ROLES = {"OWNER", "ADMIN"}


class AutomationError(Exception):
    def __init__(self, message: str, status_code: int = 400, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.errors = errors or [message]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Validation --------------------------------------------------------------------


@dataclass
class NormalizedDefinition:
    trigger: TriggerSpec | None
    trigger_configuration: dict[str, Any] = field(default_factory=dict)
    conditions: dict[str, Any] = field(default_factory=lambda: {"logic": "and", "rules": []})
    actions: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


def validate_definition(
    db: DBSession,
    *,
    workspace_id: UUID,
    trigger_type: str,
    trigger_configuration: dict[str, Any] | None,
    conditions: Any,
    actions: list[dict[str, Any]],
    brand_id: UUID | None,
    require_actions: bool = True,
) -> NormalizedDefinition:
    """Validate every part of an automation against the registries and the workspace."""
    settings = get_settings()
    result = NormalizedDefinition(trigger=None)
    try:
        spec = get_trigger(trigger_type)
    except TriggerError as exc:
        result.errors.append(str(exc))
        return result
    result.trigger = spec
    try:
        result.trigger_configuration = validate_trigger_configuration(spec, trigger_configuration)
    except TriggerError as exc:
        result.errors.append(str(exc))
    try:
        result.conditions = validate_conditions(spec, conditions)
    except ConditionError as exc:
        result.errors.extend(exc.errors)
    if brand_id is not None:
        brand = db.get(Brand, brand_id)
        if brand is None or brand.workspace_id != workspace_id:
            result.errors.append("Brand not found in this workspace.")
        elif "brand_id" not in spec.field_map():
            result.warnings.append("This trigger has no brand; the brand filter will never match.")
    if require_actions and not actions:
        result.errors.append("Add at least one action.")
    if len(actions) > settings.automation_max_actions:
        result.errors.append(f"An automation can have at most {settings.automation_max_actions} actions.")
    for position, action in enumerate(actions[: settings.automation_max_actions], start=1):
        action_type = str(action.get("action_type") or "")
        configuration = action.get("configuration") or action.get("action_configuration") or {}
        if not isinstance(configuration, dict):
            result.errors.append(f"Action {position}: configuration must be an object.")
            continue
        spec_action, _config, errors = A.validate_action(
            db, workspace_id=workspace_id, trigger=spec, action_type=action_type, configuration=configuration
        )
        result.errors.extend(f"Action {position}: {message}" for message in errors)
        if spec_action is not None and spec_action.external_side_effect:
            result.warnings.append(f"Action {position} ({spec_action.label}) requests work from Meta and is subject to the analytics refresh cooldown.")
        result.actions.append({"action_type": action_type, "configuration": configuration})
    if not result.errors and not result.conditions.get("rules"):
        result.warnings.append("No conditions: the automation runs for every event of this trigger in its scope.")
    return result


def automation_issues(db: DBSession, automation: Automation) -> list[str]:
    """Problems that would prevent the automation from being enabled or from running."""
    normalized = validate_definition(
        db,
        workspace_id=automation.workspace_id,
        trigger_type=automation.trigger_type,
        trigger_configuration=automation.trigger_configuration,
        conditions=automation.conditions,
        actions=[{"action_type": item.action_type, "configuration": item.action_configuration} for item in automation.actions],
        brand_id=automation.brand_id,
    )
    issues = list(normalized.errors)
    actor = automation_actor(db, automation)
    if actor is None:
        issues.append("The automation owner is no longer an active member of this workspace.")
    else:
        for item in automation.actions:
            spec = A.ACTIONS.get(item.action_type)
            if spec is not None and actor.role not in spec.required_roles:
                issues.append(f"Action '{spec.label}' requires the Owner or Admin role; the automation owner is a {actor.role.title()}.")
    return issues


# Lifecycle ---------------------------------------------------------------------


def _replace_actions(automation: Automation, actions: list[dict[str, Any]]) -> None:
    automation.actions.clear()
    for position, item in enumerate(actions, start=1):
        automation.actions.append(
            AutomationAction(action_type=item["action_type"], action_configuration=item["configuration"], execution_order=position)
        )


def create_automation(db: DBSession, *, workspace_id: UUID, user_id: UUID, data: dict[str, Any]) -> Automation:
    settings = get_settings()
    count = (
        db.query(Automation.id)
        .filter(Automation.workspace_id == workspace_id, Automation.status != "archived")
        .count()
    )
    if count >= settings.automation_max_per_workspace:
        raise AutomationError(f"This workspace already has the maximum of {settings.automation_max_per_workspace} automations.", 409)
    normalized = validate_definition(
        db,
        workspace_id=workspace_id,
        trigger_type=data["trigger_type"],
        trigger_configuration=data.get("trigger_configuration"),
        conditions=data.get("conditions"),
        actions=[item if isinstance(item, dict) else item.model_dump() for item in data.get("actions") or []],
        brand_id=data.get("brand_id"),
        require_actions=False,
    )
    if not normalized.valid:
        raise AutomationError("The automation configuration is invalid.", 422, normalized.errors)
    now = utc_now()
    automation = Automation(
        workspace_id=workspace_id,
        brand_id=data.get("brand_id"),
        name=data["name"],
        description=data.get("description"),
        status="draft",
        trigger_type=data["trigger_type"],
        trigger_configuration=normalized.trigger_configuration,
        conditions=normalized.conditions,
        max_executions=data.get("max_executions"),
        cooldown_seconds=int(data.get("cooldown_seconds") or 0),
        created_by=user_id,
        updated_by=user_id,
        created_at=now,
        updated_at=now,
    )
    _replace_actions(automation, normalized.actions)
    db.add(automation)
    db.flush()
    record_audit(
        db,
        action="automation.created",
        resource_type="automation",
        actor_user_id=user_id,
        workspace_id=workspace_id,
        resource_id=automation.id,
        metadata={"trigger_type": automation.trigger_type, "actions": [item.action_type for item in automation.actions]},
    )
    db.commit()
    db.refresh(automation)
    return automation


def update_automation(db: DBSession, automation: Automation, *, user_id: UUID, changes: dict[str, Any]) -> Automation:
    if automation.status == "archived":
        raise AutomationError("Archived automations cannot be edited. Duplicate it instead.", 409)
    trigger_type = changes.get("trigger_type") or automation.trigger_type
    trigger_configuration = changes["trigger_configuration"] if "trigger_configuration" in changes and changes["trigger_configuration"] is not None else automation.trigger_configuration
    if "trigger_type" in changes and changes["trigger_type"] and changes["trigger_type"] != automation.trigger_type:
        # A new trigger has a different payload schema: conditions and configuration must be supplied again.
        trigger_configuration = changes.get("trigger_configuration") or {}
        if "conditions" not in changes:
            changes["conditions"] = {"logic": "and", "rules": []}
    conditions = changes["conditions"] if "conditions" in changes else automation.conditions
    if changes.get("actions") is not None:
        actions = [item if isinstance(item, dict) else item.model_dump() for item in changes["actions"]]
    else:
        actions = [{"action_type": item.action_type, "configuration": item.action_configuration} for item in automation.actions]
    brand_id = None if changes.get("clear_brand") else changes.get("brand_id", automation.brand_id)
    normalized = validate_definition(
        db,
        workspace_id=automation.workspace_id,
        trigger_type=trigger_type,
        trigger_configuration=trigger_configuration,
        conditions=conditions,
        actions=actions,
        brand_id=brand_id,
        require_actions=automation.status == "enabled",
    )
    if not normalized.valid:
        raise AutomationError("The automation configuration is invalid.", 422, normalized.errors)
    if "name" in changes and changes["name"]:
        automation.name = changes["name"]
    if "description" in changes:
        automation.description = changes["description"]
    automation.brand_id = brand_id
    automation.trigger_type = trigger_type
    automation.trigger_configuration = normalized.trigger_configuration
    automation.conditions = normalized.conditions
    if changes.get("clear_max_executions"):
        automation.max_executions = None
    elif changes.get("max_executions") is not None:
        automation.max_executions = changes["max_executions"]
    if changes.get("cooldown_seconds") is not None:
        automation.cooldown_seconds = changes["cooldown_seconds"]
    if changes.get("actions") is not None or "trigger_type" in changes:
        _replace_actions(automation, normalized.actions)
    automation.updated_by = user_id
    automation.updated_at = utc_now()
    record_audit(
        db,
        action="automation.updated",
        resource_type="automation",
        actor_user_id=user_id,
        workspace_id=automation.workspace_id,
        resource_id=automation.id,
        metadata={"fields": sorted(key for key in changes if changes[key] is not None)},
    )
    db.commit()
    db.refresh(automation)
    return automation


def enable_automation(db: DBSession, automation: Automation, *, membership: WorkspaceMembership) -> Automation:
    if membership.role not in ADMIN_ROLES:
        raise AutomationError("Only workspace Owners and Admins can enable automations.", 403)
    if automation.status == "archived":
        raise AutomationError("Archived automations cannot be enabled.", 409)
    if automation.status == "enabled":
        return automation
    if not automation.actions:
        raise AutomationError("Add at least one action before enabling the automation.", 422)
    # The enabling admin becomes the owner whose permissions the automation runs with.
    automation.updated_by = membership.user_id
    issues = automation_issues(db, automation)
    if issues:
        raise AutomationError("The automation cannot be enabled.", 422, issues)
    now = utc_now()
    automation.status = "enabled"
    automation.enabled_at = now
    automation.paused_at = None
    automation.updated_at = now
    record_audit(
        db,
        action="automation.enabled",
        resource_type="automation",
        actor_user_id=membership.user_id,
        workspace_id=automation.workspace_id,
        resource_id=automation.id,
        metadata={"trigger_type": automation.trigger_type},
    )
    db.commit()
    db.refresh(automation)
    return automation


def pause_automation(db: DBSession, automation: Automation, *, user_id: UUID) -> Automation:
    if automation.status != "enabled":
        raise AutomationError(f"Only enabled automations can be paused (current status: {automation.status}).", 409)
    now = utc_now()
    automation.status = "paused"
    automation.paused_at = now
    automation.updated_at = now
    record_audit(db, action="automation.paused", resource_type="automation", actor_user_id=user_id, workspace_id=automation.workspace_id, resource_id=automation.id)
    db.commit()
    db.refresh(automation)
    return automation


def resume_automation(db: DBSession, automation: Automation, *, membership: WorkspaceMembership) -> Automation:
    if automation.status != "paused":
        raise AutomationError(f"Only paused automations can be resumed (current status: {automation.status}).", 409)
    automation.status = "draft"  # enable_automation re-validates and records the transition
    enabled = enable_automation(db, automation, membership=membership)
    record_audit(db, action="automation.resumed", resource_type="automation", actor_user_id=membership.user_id, workspace_id=automation.workspace_id, resource_id=automation.id)
    db.commit()
    return enabled


def archive_automation(db: DBSession, automation: Automation, *, user_id: UUID) -> Automation:
    if automation.status == "archived":
        return automation
    now = utc_now()
    automation.status = "archived"
    automation.archived_at = now
    automation.updated_at = now
    cancelled = (
        db.query(AutomationExecution)
        .filter(AutomationExecution.automation_id == automation.id, AutomationExecution.status == "pending")
        .all()
    )
    for execution in cancelled:
        execution.status = "cancelled"
        execution.completed_at = now
        execution.error_message = "The automation was archived before this execution ran."
    record_audit(
        db,
        action="automation.archived",
        resource_type="automation",
        actor_user_id=user_id,
        workspace_id=automation.workspace_id,
        resource_id=automation.id,
        metadata={"cancelled_pending_executions": len(cancelled)},
    )
    db.commit()
    db.refresh(automation)
    return automation


def delete_automation(db: DBSession, automation: Automation, *, user_id: UUID) -> None:
    if automation.status not in {"draft", "archived"}:
        raise AutomationError("Pause and archive the automation before deleting it.", 409)
    record_audit(
        db,
        action="automation.deleted",
        resource_type="automation",
        actor_user_id=user_id,
        workspace_id=automation.workspace_id,
        resource_id=automation.id,
        metadata={"name": automation.name, "trigger_type": automation.trigger_type},
    )
    db.delete(automation)
    db.commit()


def duplicate_automation(db: DBSession, automation: Automation, *, user_id: UUID) -> Automation:
    settings = get_settings()
    count = (
        db.query(Automation.id)
        .filter(Automation.workspace_id == automation.workspace_id, Automation.status != "archived")
        .count()
    )
    if count >= settings.automation_max_per_workspace:
        raise AutomationError(f"This workspace already has the maximum of {settings.automation_max_per_workspace} automations.", 409)
    now = utc_now()
    copy = Automation(
        workspace_id=automation.workspace_id,
        brand_id=automation.brand_id,
        name=f"{automation.name} (copy)"[:120],
        description=automation.description,
        status="draft",
        trigger_type=automation.trigger_type,
        trigger_configuration=dict(automation.trigger_configuration or {}),
        conditions=dict(automation.conditions or {}),
        max_executions=automation.max_executions,
        cooldown_seconds=automation.cooldown_seconds,
        created_by=user_id,
        updated_by=user_id,
        created_at=now,
        updated_at=now,
    )
    _replace_actions(copy, [{"action_type": item.action_type, "configuration": dict(item.action_configuration or {})} for item in automation.actions])
    db.add(copy)
    db.flush()
    record_audit(
        db,
        action="automation.duplicated",
        resource_type="automation",
        actor_user_id=user_id,
        workspace_id=automation.workspace_id,
        resource_id=copy.id,
        metadata={"source_automation_id": str(automation.id)},
    )
    db.commit()
    db.refresh(copy)
    return copy


# Dry run -------------------------------------------------------------------------

DRY_RUN_NOTICE = (
    "Simulated result. Nothing was executed: no notifications, tasks, assignments or analytics requests were created."
)


def dry_run(
    db: DBSession,
    *,
    workspace_id: UUID,
    actor: WorkspaceMembership | None,
    name: str,
    trigger_type: str,
    trigger_configuration: dict[str, Any] | None,
    conditions: Any,
    actions: list[dict[str, Any]],
    brand_id: UUID | None,
    payload_source: str = "sample",
    payload_overrides: dict[str, Any] | None = None,
    automation: Automation | None = None,
) -> dict[str, Any]:
    """Evaluate a configuration against sample or recorded event data without side effects."""
    now = utc_now()
    normalized = validate_definition(
        db,
        workspace_id=workspace_id,
        trigger_type=trigger_type,
        trigger_configuration=trigger_configuration,
        conditions=conditions,
        actions=actions,
        brand_id=brand_id,
    )
    errors = list(normalized.errors)
    spec = normalized.trigger
    if spec is None:
        return {
            "simulated": True,
            "generated_at": now,
            "trigger_type": trigger_type,
            "payload_source": payload_source,
            "event_id": None,
            "payload": {},
            "conditions_passed": False,
            "condition_results": {},
            "would_execute": False,
            "actions": [],
            "errors": errors,
            "notice": DRY_RUN_NOTICE,
        }

    event_id: UUID | None = None
    payload = dict(spec.sample)
    source = "sample"
    if payload_source == "latest_event":
        event = (
            db.query(AutomationEvent)
            .filter(AutomationEvent.workspace_id == workspace_id, AutomationEvent.event_type == spec.type)
            .order_by(AutomationEvent.occurred_at.desc())
            .first()
        )
        if event is not None:
            payload = dict(event.event_payload or {})
            event_id = event.id
            source = "latest_event"
        else:
            errors.append("No recorded event of this type exists in the workspace yet; the built-in sample was used instead.")
    if payload_overrides:
        override_errors = payload_errors(spec, payload_overrides)
        errors.extend(override_errors)
        if not override_errors:
            payload.update(payload_overrides)
    payload = normalize_payload(spec, payload)

    condition_result = evaluate_conditions(spec, normalized.conditions, payload)
    conditions_passed = condition_result.passed
    brand_ok = brand_id is None or str(payload.get("brand_id") or "") == str(brand_id)
    if not brand_ok:
        errors.append("The event's brand does not match the automation's brand filter; the automation would not run.")
    deadline_ok = True
    if spec.type == "APPROVAL_REMINDER_DUE":
        deadline = int(normalized.trigger_configuration.get("deadline_hours") or 0)
        if (payload.get("pending_hours") or 0) < deadline:
            deadline_ok = False
            errors.append(f"The approval has waited {payload.get('pending_hours') or 0}h, less than the {deadline}h deadline; the automation would not run yet.")

    shadow = automation or Automation(
        id=UUID(int=0),
        workspace_id=workspace_id,
        brand_id=brand_id,
        name=name,
        status="draft",
        trigger_type=spec.type,
        trigger_configuration=normalized.trigger_configuration,
        conditions=normalized.conditions,
    )
    action_results: list[dict[str, Any]] = []
    for position, action in enumerate(normalized.actions, start=1):
        spec_action = A.ACTIONS.get(action["action_type"])
        label = spec_action.label if spec_action else action["action_type"]
        prefix = f"Action {position}: "
        action_errors = [message[len(prefix):] for message in normalized.errors if message.startswith(prefix)]
        detail = ""
        if spec_action is not None and not action_errors:
            try:
                A.check_actor_permission(spec_action, actor)
                config = spec_action.config_model.model_validate(action["configuration"])
                ctx = A.ActionContext(db=db, automation=shadow, execution=None, spec=spec, payload=payload, now=now, actor=actor, step_order=position)
                detail = spec_action.simulate(ctx, config)
            except A.ActionError as exc:
                action_errors.append(str(exc))
        action_results.append(
            {
                "order": position,
                "action_type": action["action_type"],
                "label": label,
                "status": "would_run" if not action_errors else "blocked",
                "detail": detail or ("Blocked: " + "; ".join(action_errors) if action_errors else ""),
                "errors": action_errors,
            }
        )
    would_execute = bool(normalized.actions) and conditions_passed and brand_ok and deadline_ok and not normalized.errors
    if not normalized.actions:
        errors.append("Add at least one action to test.")
    result = {
        "simulated": True,
        "generated_at": now,
        "trigger_type": spec.type,
        "payload_source": source,
        "event_id": event_id,
        "payload": payload,
        "conditions_passed": conditions_passed,
        "condition_results": condition_result.as_dict(),
        "would_execute": would_execute,
        "actions": action_results,
        "errors": list(dict.fromkeys(errors)),
        "notice": DRY_RUN_NOTICE,
    }
    # A dry run must leave no trace in the database other than the stored result on a saved automation.
    db.rollback()
    if automation is not None:
        automation = db.get(Automation, automation.id)
        automation.last_dry_run = {**result, "generated_at": now.isoformat(), "event_id": str(event_id) if event_id else None}
        automation.last_dry_run_at = now
        record_audit(
            db,
            action="automation.dry_run",
            resource_type="automation",
            actor_user_id=actor.user_id if actor else None,
            workspace_id=workspace_id,
            resource_id=automation.id,
            metadata={"would_execute": would_execute, "payload_source": source},
        )
        db.commit()
    return result
