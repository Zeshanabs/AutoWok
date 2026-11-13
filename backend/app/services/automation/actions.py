"""Allowlisted action registry.

Every action has a pydantic configuration model (``extra="forbid"``), the role
the automation's owner must still hold when it runs, the triggers it may be
combined with, the payload fields it needs, a ``run`` function with real side
effects and a ``simulate`` function used by dry runs. Nothing here performs
HTTP requests, shell commands or raw queries; actions only call existing
Autowok services (notifications, tasks, assignment, analytics refresh).

Side effects are idempotent per execution step: notifications and tasks use a
``dedupe_key`` derived from the execution and step, so a retried execution
never produces duplicates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession

from app.models import (
    Automation,
    AutomationExecution,
    ContentProject,
    ContentTask,
    SocialAccount,
    User,
    WorkspaceMembership,
)
from app.services import notifications as N
from app.services.audit import record_audit
from app.services.automation.registry import TriggerSpec
from app.services.automation.templates import render, unknown_placeholders

ADMIN_ROLES = frozenset({"OWNER", "ADMIN"})
MEMBER_ROLES = frozenset({"OWNER", "ADMIN", "MEMBER"})
CONTENT_TRIGGERS = frozenset(
    {
        "CONTENT_CREATED",
        "CONTENT_SUBMITTED_FOR_APPROVAL",
        "CONTENT_APPROVED",
        "CONTENT_REJECTED",
        "CONTENT_UPDATED",
        "TEAM_MEMBER_ASSIGNED",
        "APPROVAL_REMINDER_DUE",
        "POST_SCHEDULED",
        "POST_PUBLISHING",
        "POST_PUBLISHED",
        "POST_PUBLISH_FAILED",
        "POST_CANCELLED",
    }
)
APPROVAL_TRIGGERS = frozenset({"CONTENT_SUBMITTED_FOR_APPROVAL", "APPROVAL_REMINDER_DUE"})
PUBLISH_FAILURE_TRIGGERS = frozenset({"POST_PUBLISH_FAILED"})
ANALYTICS_REFRESH_TRIGGERS = frozenset({"POST_PUBLISHED", "ANALYTICS_SYNC_FAILED"})
LABEL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 _\-]{0,39}$"


class ActionError(Exception):
    """Permanent action failure (configuration, permission, missing data)."""


class ActionRetryable(ActionError):
    """Temporary failure: the execution may be retried with backoff."""


class ActionUnauthorized(ActionError):
    pass


@dataclass
class ActionContext:
    db: DBSession
    automation: Automation
    execution: AutomationExecution | None
    spec: TriggerSpec
    payload: dict[str, Any]
    now: datetime
    actor: WorkspaceMembership | None
    step_order: int

    @property
    def workspace_id(self) -> UUID:
        return self.automation.workspace_id

    def dedupe(self, suffix: str = "") -> str:
        base = f"exec:{self.execution.id}:{self.step_order}" if self.execution else f"dry:{self.automation.id}:{self.step_order}"
        return f"{base}:{suffix}" if suffix else base

    def uuid(self, name: str) -> UUID | None:
        value = self.payload.get(name)
        try:
            return UUID(str(value)) if value else None
        except ValueError:
            return None


@dataclass
class StepResult:
    summary: str
    details: dict[str, Any]


# Configuration models -----------------------------------------------------------


class ActionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotifyMemberConfig(ActionConfig):
    user_id: UUID
    title: str | None = Field(default=None, max_length=120)
    message: str = Field(min_length=1, max_length=500)


class NotifyAdminsConfig(ActionConfig):
    title: str | None = Field(default=None, max_length=120)
    message: str = Field(min_length=1, max_length=500)


class NotifyContentOwnerConfig(ActionConfig):
    target: Literal["creator", "assignee", "actor", "requester"] = "creator"
    title: str | None = Field(default=None, max_length=120)
    message: str = Field(min_length=1, max_length=500)


class AssignContentConfig(ActionConfig):
    user_id: UUID
    notify: bool = True


class CreateTaskConfig(ActionConfig):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    kind: Literal["task", "followup", "analytics_followup"] = "task"
    assignee_type: Literal["none", "member", "creator", "assignee", "requester"] = "none"
    assignee_user_id: UUID | None = None
    due_in_hours: int | None = Field(default=None, ge=1, le=720)


class AddLabelConfig(ActionConfig):
    label: str = Field(pattern=LABEL_PATTERN)


class CreateApprovalReminderConfig(ActionConfig):
    message: str | None = Field(default=None, max_length=500)
    notify_reviewers: bool = True


class RecordPublishingIncidentConfig(ActionConfig):
    severity: Literal["low", "medium", "high"] = "medium"
    note: str | None = Field(default=None, max_length=500)
    notify_admins: bool = True


class RequestAnalyticsRefreshConfig(ActionConfig):
    pass


# Helpers ------------------------------------------------------------------------


def _member(db: DBSession, workspace_id: UUID, user_id: UUID | None) -> WorkspaceMembership | None:
    if user_id is None:
        return None
    return (
        db.query(WorkspaceMembership)
        .filter(WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.user_id == user_id)
        .first()
    )


def _user_name(db: DBSession, user_id: UUID | None) -> str:
    user = db.get(User, user_id) if user_id else None
    return user.full_name if user else "Unknown member"


def _project(ctx: ActionContext) -> ContentProject:
    project_id = ctx.uuid("project_id")
    project = ctx.db.get(ContentProject, project_id) if project_id else None
    if project is None or project.workspace_id != ctx.workspace_id:
        raise ActionError("The content post referenced by this event no longer exists in the workspace.")
    return project


def _resolve_target(ctx: ActionContext, target: str) -> UUID | None:
    mapping = {
        "creator": "created_by",
        "assignee": "assigned_to",
        "actor": "actor_user_id",
        "requester": "requested_by",
    }
    return ctx.uuid(mapping[target])


def _default_title(ctx: ActionContext) -> str:
    return ctx.spec.label


def _resource(ctx: ActionContext) -> tuple[str | None, str | None]:
    for name, resource_type in (
        ("project_id", "content_project"),
        ("publication_id", "content_publication"),
        ("scheduled_post_id", "scheduled_post"),
        ("sync_job_id", "analytics_sync_job"),
    ):
        if ctx.payload.get(name):
            return resource_type, str(ctx.payload[name])
    return None, None


def _notify_users(ctx: ActionContext, user_ids: list[UUID], *, title: str | None, message: str, category: str) -> StepResult:
    resource_type, resource_id = _resource(ctx)
    rendered_title = render(title, ctx.payload) if title else f"{ctx.automation.name}: {_default_title(ctx)}"
    rendered_message = render(message, ctx.payload)
    created = N.notify_many(
        ctx.db,
        user_ids,
        workspace_id=ctx.workspace_id,
        dedupe_prefix=ctx.dedupe(),
        category=category,
        title=rendered_title,
        message=rendered_message,
        resource_type=resource_type,
        resource_id=resource_id,
        automation_id=ctx.automation.id,
        execution_id=ctx.execution.id if ctx.execution else None,
    )
    names = [_user_name(ctx.db, user_id) for user_id in dict.fromkeys(user_ids)]
    return StepResult(
        f"Notified {len(created)} member(s): {', '.join(names) if names else 'nobody'}",
        {"recipients": [str(user_id) for user_id in dict.fromkeys(user_ids)], "created": len(created)},
    )


def _create_task(
    ctx: ActionContext,
    *,
    kind: str,
    title: str,
    description: str | None,
    assigned_to: UUID | None,
    due_at: datetime | None = None,
    severity: str | None = None,
    project_id: UUID | None = None,
    publication_id: UUID | None = None,
) -> ContentTask | None:
    dedupe_key = ctx.dedupe("task")
    existing = ctx.db.query(ContentTask).filter(ContentTask.dedupe_key == dedupe_key).first()
    if existing is not None:
        return existing
    if assigned_to is not None and _member(ctx.db, ctx.workspace_id, assigned_to) is None:
        assigned_to = None
    task = ContentTask(
        workspace_id=ctx.workspace_id,
        project_id=project_id,
        publication_id=publication_id,
        kind=kind,
        title=render(title, ctx.payload)[:200] or "Task",
        description=render(description, ctx.payload)[:1000] if description else None,
        severity=severity,
        status="open",
        assigned_to=assigned_to,
        created_by=ctx.actor.user_id if ctx.actor else None,
        automation_id=ctx.automation.id,
        execution_id=ctx.execution.id if ctx.execution else None,
        dedupe_key=dedupe_key,
        due_at=due_at,
    )
    ctx.db.add(task)
    return task


# Action implementations ----------------------------------------------------------


def run_notify_member(ctx: ActionContext, config: NotifyMemberConfig) -> StepResult:
    if _member(ctx.db, ctx.workspace_id, config.user_id) is None:
        raise ActionError("The selected recipient is no longer a member of this workspace.")
    return _notify_users(ctx, [config.user_id], title=config.title, message=config.message, category="automation")


def simulate_notify_member(ctx: ActionContext, config: NotifyMemberConfig) -> str:
    if _member(ctx.db, ctx.workspace_id, config.user_id) is None:
        raise ActionError("The selected recipient is no longer a member of this workspace.")
    return f"Would notify {_user_name(ctx.db, config.user_id)}: “{render(config.message, ctx.payload)}”"


def run_notify_admins(ctx: ActionContext, config: NotifyAdminsConfig) -> StepResult:
    admins = N.workspace_member_ids(ctx.db, ctx.workspace_id, roles=ADMIN_ROLES)
    return _notify_users(ctx, admins, title=config.title, message=config.message, category="automation")


def simulate_notify_admins(ctx: ActionContext, config: NotifyAdminsConfig) -> str:
    admins = N.workspace_member_ids(ctx.db, ctx.workspace_id, roles=ADMIN_ROLES)
    names = ", ".join(_user_name(ctx.db, user_id) for user_id in admins)
    return f"Would notify {len(admins)} administrator(s) ({names}): “{render(config.message, ctx.payload)}”"


def run_notify_content_owner(ctx: ActionContext, config: NotifyContentOwnerConfig) -> StepResult:
    user_id = _resolve_target(ctx, config.target)
    if user_id is None:
        return StepResult(f"No {config.target} on this event; nobody to notify.", {"recipients": [], "created": 0})
    if _member(ctx.db, ctx.workspace_id, user_id) is None:
        return StepResult(f"The {config.target} is no longer a workspace member; skipped.", {"recipients": [], "created": 0})
    return _notify_users(ctx, [user_id], title=config.title, message=config.message, category="automation")


def simulate_notify_content_owner(ctx: ActionContext, config: NotifyContentOwnerConfig) -> str:
    user_id = _resolve_target(ctx, config.target)
    if user_id is None:
        return f"Would skip: the event has no {config.target}."
    return f"Would notify the {config.target} ({_user_name(ctx.db, user_id)}): “{render(config.message, ctx.payload)}”"


def run_assign_content(ctx: ActionContext, config: AssignContentConfig) -> StepResult:
    from app.services.automation import events

    project = _project(ctx)
    if _member(ctx.db, ctx.workspace_id, config.user_id) is None:
        raise ActionError("The selected assignee is no longer a member of this workspace.")
    if project.assigned_to == config.user_id:
        return StepResult(f"Already assigned to {_user_name(ctx.db, config.user_id)}.", {"assigned_to": str(config.user_id), "changed": False})
    project.assigned_to = config.user_id
    actor_id = ctx.actor.user_id if ctx.actor else None
    events.emit_team_member_assigned(ctx.db, project, assigned_by=actor_id)
    record_audit(
        ctx.db,
        action="content.assigned",
        resource_type="content_project",
        actor_user_id=actor_id,
        workspace_id=ctx.workspace_id,
        resource_id=project.id,
        metadata={"assigned_to": str(config.user_id), "automation_id": str(ctx.automation.id)},
    )
    if config.notify:
        N.notify(
            ctx.db,
            workspace_id=ctx.workspace_id,
            user_id=config.user_id,
            category="assignment",
            title="Content assigned to you",
            message=f"“{project.title}” was assigned to you by the automation “{ctx.automation.name}”.",
            resource_type="content_project",
            resource_id=project.id,
            automation_id=ctx.automation.id,
            execution_id=ctx.execution.id if ctx.execution else None,
            dedupe_key=ctx.dedupe("assign-notify"),
        )
    return StepResult(f"Assigned “{project.title}” to {_user_name(ctx.db, config.user_id)}.", {"assigned_to": str(config.user_id), "changed": True})


def simulate_assign_content(ctx: ActionContext, config: AssignContentConfig) -> str:
    if _member(ctx.db, ctx.workspace_id, config.user_id) is None:
        raise ActionError("The selected assignee is no longer a member of this workspace.")
    return f"Would assign the content post to {_user_name(ctx.db, config.user_id)}" + (" and notify them." if config.notify else ".")


def _task_assignee(ctx: ActionContext, assignee_type: str, assignee_user_id: UUID | None) -> UUID | None:
    if assignee_type == "member":
        return assignee_user_id
    if assignee_type == "creator":
        return ctx.uuid("created_by")
    if assignee_type == "assignee":
        return ctx.uuid("assigned_to")
    if assignee_type == "requester":
        return ctx.uuid("requested_by")
    return None


def run_create_task(ctx: ActionContext, config: CreateTaskConfig) -> StepResult:
    assignee = _task_assignee(ctx, config.assignee_type, config.assignee_user_id)
    due_at = ctx.now + timedelta(hours=config.due_in_hours) if config.due_in_hours else None
    task = _create_task(
        ctx,
        kind=config.kind,
        title=config.title,
        description=config.description,
        assigned_to=assignee,
        due_at=due_at,
        project_id=ctx.uuid("project_id"),
        publication_id=ctx.uuid("publication_id"),
    )
    if task is not None and task.assigned_to is not None:
        N.notify(
            ctx.db,
            workspace_id=ctx.workspace_id,
            user_id=task.assigned_to,
            category="task",
            title="New task assigned to you",
            message=task.title,
            resource_type="content_task",
            resource_id=task.id,
            automation_id=ctx.automation.id,
            execution_id=ctx.execution.id if ctx.execution else None,
            dedupe_key=ctx.dedupe("task-notify"),
        )
    return StepResult(f"Created task “{task.title}”." if task else "Task already existed.", {"task_id": str(task.id) if task else None})


def simulate_create_task(ctx: ActionContext, config: CreateTaskConfig) -> str:
    assignee = _task_assignee(ctx, config.assignee_type, config.assignee_user_id)
    who = f" assigned to {_user_name(ctx.db, assignee)}" if assignee else ""
    return f"Would create a {config.kind} “{render(config.title, ctx.payload)}”{who}."


def run_add_label(ctx: ActionContext, config: AddLabelConfig) -> StepResult:
    project = _project(ctx)
    labels = list(project.labels or [])
    if config.label in labels:
        return StepResult(f"Label “{config.label}” already present.", {"label": config.label, "changed": False})
    if len(labels) >= 20:
        raise ActionError("The content post already has the maximum number of labels (20).")
    project.labels = labels + [config.label]
    return StepResult(f"Added label “{config.label}” to “{project.title}”.", {"label": config.label, "changed": True})


def simulate_add_label(ctx: ActionContext, config: AddLabelConfig) -> str:
    return f"Would add the internal label “{config.label}” to the content post."


def run_create_approval_reminder(ctx: ActionContext, config: CreateApprovalReminderConfig) -> StepResult:
    project = _project(ctx)
    if project.status not in {"ready_for_review", "in_review"}:
        return StepResult("The content post is no longer waiting for approval; no reminder created.", {"created": False})
    message = render(config.message, ctx.payload) if config.message else f"“{project.title}” is still waiting for approval."
    task = _create_task(
        ctx,
        kind="reminder",
        title=f"Approval reminder: {project.title}",
        description=message,
        assigned_to=None,
        project_id=project.id,
    )
    notified = 0
    if config.notify_reviewers:
        admins = N.workspace_member_ids(ctx.db, ctx.workspace_id, roles=ADMIN_ROLES)
        notified = len(
            N.notify_many(
                ctx.db,
                admins,
                workspace_id=ctx.workspace_id,
                dedupe_prefix=ctx.dedupe("reminder"),
                category="approval_reminder",
                title="Approval reminder",
                message=message,
                resource_type="content_project",
                resource_id=project.id,
                automation_id=ctx.automation.id,
                execution_id=ctx.execution.id if ctx.execution else None,
            )
        )
    return StepResult(f"Created an approval reminder and notified {notified} reviewer(s).", {"task_id": str(task.id) if task else None, "notified": notified})


def simulate_create_approval_reminder(ctx: ActionContext, config: CreateApprovalReminderConfig) -> str:
    admins = N.workspace_member_ids(ctx.db, ctx.workspace_id, roles=ADMIN_ROLES)
    return "Would create an approval reminder task" + (f" and notify {len(admins)} reviewer(s)." if config.notify_reviewers else ".")


def run_record_publishing_incident(ctx: ActionContext, config: RecordPublishingIncidentConfig) -> StepResult:
    publication_id = ctx.uuid("publication_id")
    if publication_id is None:
        raise ActionError("This event has no publishing job to record an incident for.")
    description = render(config.note, ctx.payload) if config.note else None
    summary = (
        f"Publishing failed on {ctx.payload.get('platform') or 'unknown platform'}"
        f" ({ctx.payload.get('error_category') or 'unknown error'}, code {ctx.payload.get('error_code') or '—'})."
    )
    task = _create_task(
        ctx,
        kind="incident",
        title=f"Publishing incident: {ctx.payload.get('title') or 'content post'}",
        description="\n".join(part for part in (summary, description) if part),
        assigned_to=None,
        severity=config.severity,
        project_id=ctx.uuid("project_id"),
        publication_id=publication_id,
    )
    record_audit(
        ctx.db,
        action="publishing.incident_recorded",
        resource_type="content_publication",
        workspace_id=ctx.workspace_id,
        resource_id=publication_id,
        metadata={"severity": config.severity, "automation_id": str(ctx.automation.id)},
    )
    notified = 0
    if config.notify_admins:
        notified = len(
            N.notify_admins(
                ctx.db,
                workspace_id=ctx.workspace_id,
                dedupe_prefix=ctx.dedupe("incident"),
                category="publishing_incident",
                title=f"Publishing incident ({config.severity})",
                message=summary,
                resource_type="content_publication",
                resource_id=publication_id,
                automation_id=ctx.automation.id,
                execution_id=ctx.execution.id if ctx.execution else None,
            )
        )
    return StepResult(f"Recorded a {config.severity} publishing incident; notified {notified} administrator(s).", {"task_id": str(task.id) if task else None, "notified": notified})


def simulate_record_publishing_incident(ctx: ActionContext, config: RecordPublishingIncidentConfig) -> str:
    return f"Would record a {config.severity} publishing incident" + (" and notify administrators." if config.notify_admins else ".")


def run_request_analytics_refresh(ctx: ActionContext, config: RequestAnalyticsRefreshConfig) -> StepResult:
    from app.services.analytics import sync as S

    account_id = ctx.uuid("social_account_id")
    account = ctx.db.get(SocialAccount, account_id) if account_id else None
    if account is None or account.workspace_id != ctx.workspace_id:
        raise ActionError("The social account referenced by this event no longer exists in the workspace.")
    if ctx.actor is None:
        raise ActionUnauthorized("The automation owner is no longer a workspace member.")
    try:
        job = S.request_sync(ctx.db, account=account, requested_by=ctx.actor.user_id, now=ctx.now, enqueue=False)
    except S.SyncConflict as exc:
        # Cooldowns and in-progress jobs are expected; report and move on.
        return StepResult(f"Analytics refresh not requested: {exc}", {"requested": False, "reason": str(exc)})
    return StepResult(f"Requested an analytics refresh for {account.display_name}.", {"requested": True, "sync_job_id": str(job.id)})


def simulate_request_analytics_refresh(ctx: ActionContext, config: RequestAnalyticsRefreshConfig) -> str:
    from app.services.analytics import sync as S

    account_id = ctx.uuid("social_account_id")
    account = ctx.db.get(SocialAccount, account_id) if account_id else None
    if account is None or account.workspace_id != ctx.workspace_id:
        return "Would skip: the social account is not available in this workspace (sample data)."
    eligibility = S.analytics_eligibility(account)
    if not eligibility["can_sync"]:
        return f"Would skip: {' '.join(eligibility['reasons'])}"
    return f"Would request an analytics refresh for {account.display_name} (subject to the refresh cooldown)."


# Registry -----------------------------------------------------------------------


@dataclass(frozen=True)
class ActionSpec:
    type: str
    label: str
    description: str
    category: str
    config_model: type[ActionConfig]
    required_roles: frozenset[str]
    allowed_triggers: frozenset[str] | None
    required_fields: tuple[str, ...]
    run: Callable[[ActionContext, Any], StepResult]
    simulate: Callable[[ActionContext, Any], str]
    external_side_effect: bool = False

    def as_dict(self) -> dict[str, Any]:
        schema = self.config_model.model_json_schema()
        return {
            "type": self.type,
            "label": self.label,
            "description": self.description,
            "category": self.category,
            "required_role": "ADMIN" if self.required_roles == ADMIN_ROLES else "MEMBER",
            "allowed_triggers": sorted(self.allowed_triggers) if self.allowed_triggers else None,
            "required_fields": list(self.required_fields),
            "configuration_schema": schema,
        }


ACTIONS: dict[str, ActionSpec] = {
    spec.type: spec
    for spec in (
        ActionSpec("notify_member", "Notify a workspace member", "Send an in-app notification to one member.", "notification", NotifyMemberConfig, MEMBER_ROLES, None, (), run_notify_member, simulate_notify_member),
        ActionSpec("notify_admins", "Notify workspace administrators", "Send an in-app notification to every Owner and Admin.", "notification", NotifyAdminsConfig, MEMBER_ROLES, None, (), run_notify_admins, simulate_notify_admins),
        ActionSpec("notify_content_owner", "Notify the creator, assignee or actor", "Send an in-app notification to a person referenced by the event.", "notification", NotifyContentOwnerConfig, MEMBER_ROLES, None, (), run_notify_content_owner, simulate_notify_content_owner),
        ActionSpec("assign_content", "Assign content to a team member", "Set the assignee of the content post.", "content", AssignContentConfig, ADMIN_ROLES, CONTENT_TRIGGERS, ("project_id",), run_assign_content, simulate_assign_content),
        ActionSpec("create_task", "Create an internal task", "Create a follow-up task, optionally assigned and with a due date.", "content", CreateTaskConfig, MEMBER_ROLES, None, (), run_create_task, simulate_create_task),
        ActionSpec("add_label", "Add an internal label", "Add a label to the content post (internal metadata; the content itself is unchanged).", "content", AddLabelConfig, MEMBER_ROLES, CONTENT_TRIGGERS, ("project_id",), run_add_label, simulate_add_label),
        ActionSpec("create_approval_reminder", "Create an approval reminder", "Create a reminder task and notify reviewers while the post is awaiting approval.", "content", CreateApprovalReminderConfig, MEMBER_ROLES, APPROVAL_TRIGGERS, ("project_id",), run_create_approval_reminder, simulate_create_approval_reminder),
        ActionSpec("record_publishing_incident", "Record a publishing incident", "Record an internal incident for a failed publication and notify administrators.", "publishing", RecordPublishingIncidentConfig, MEMBER_ROLES, PUBLISH_FAILURE_TRIGGERS, ("publication_id",), run_record_publishing_incident, simulate_record_publishing_incident),
        ActionSpec("request_analytics_refresh", "Request an analytics refresh", "Request an eligible analytics synchronization for the event's account (cooldowns apply).", "analytics", RequestAnalyticsRefreshConfig, ADMIN_ROLES, ANALYTICS_REFRESH_TRIGGERS, ("social_account_id",), run_request_analytics_refresh, simulate_request_analytics_refresh, True),
    )
}


def get_action(action_type: str) -> ActionSpec:
    spec = ACTIONS.get(action_type)
    if spec is None:
        raise ActionError(f"Unknown action type: {action_type}")
    return spec


def list_actions() -> list[dict[str, Any]]:
    return [spec.as_dict() for spec in ACTIONS.values()]


def validate_action(
    db: DBSession,
    *,
    workspace_id: UUID,
    trigger: TriggerSpec,
    action_type: str,
    configuration: dict[str, Any] | None,
) -> tuple[ActionSpec | None, Any, list[str]]:
    """Validate an action against the allowlist, its schema, the trigger and the workspace."""
    errors: list[str] = []
    spec = ACTIONS.get(action_type or "")
    if spec is None:
        return None, None, [f"Action type '{action_type}' is not allowed."]
    if spec.allowed_triggers is not None and trigger.type not in spec.allowed_triggers:
        errors.append(f"Action '{spec.label}' cannot be used with the trigger {trigger.type}.")
    known = trigger.field_map()
    for name in spec.required_fields:
        if name not in known:
            errors.append(f"Action '{spec.label}' needs the field '{name}', which the trigger {trigger.type} does not provide.")
    try:
        config = spec.config_model.model_validate(configuration or {})
    except Exception as exc:  # pydantic.ValidationError
        details = getattr(exc, "errors", None)
        if callable(details):
            for item in details():
                location = ".".join(str(part) for part in item.get("loc", ()))
                errors.append(f"{spec.label}: {location + ': ' if location else ''}{item.get('msg')}")
        else:
            errors.append(f"{spec.label}: invalid configuration.")
        return spec, None, errors
    for attribute in ("title", "message", "description", "note"):
        text = getattr(config, attribute, None)
        if isinstance(text, str):
            unknown = unknown_placeholders(trigger, text)
            if unknown:
                errors.append(f"{spec.label}: unknown placeholder(s) {', '.join('{' + name + '}' for name in unknown)} in {attribute}.")
    for attribute in ("user_id", "assignee_user_id"):
        user_id = getattr(config, attribute, None)
        if user_id is not None and _member(db, workspace_id, user_id) is None:
            errors.append(f"{spec.label}: the selected member does not belong to this workspace.")
    if isinstance(config, CreateTaskConfig) and config.assignee_type == "member" and config.assignee_user_id is None:
        errors.append(f"{spec.label}: choose the member to assign the task to.")
    target_fields = {"creator": "created_by", "assignee": "assigned_to", "actor": "actor_user_id", "requester": "requested_by"}
    target = getattr(config, "target", None) or (config.assignee_type if isinstance(config, CreateTaskConfig) else None)
    if target in target_fields and target_fields[target] not in known:
        errors.append(f"{spec.label}: the trigger {trigger.type} has no {target} (field '{target_fields[target]}'); choose another recipient.")
    return spec, config, errors


def check_actor_permission(spec: ActionSpec, actor: WorkspaceMembership | None) -> None:
    if actor is None:
        raise ActionUnauthorized("The automation owner is no longer a member of this workspace.")
    if actor.role not in spec.required_roles:
        raise ActionUnauthorized(f"Action '{spec.label}' requires the Owner or Admin role; the automation owner is a {actor.role.title()}.")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
