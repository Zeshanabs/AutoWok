"""Trigger registry.

Every trigger has a stable identifier, a documented payload schema (typed
fields), a sample payload for dry runs, and the entity type it describes.
Payloads are normalized against the schema when an event is emitted: unknown
fields are dropped, values are coerced to the declared type, and anything that
cannot be coerced becomes ``None``. Tokens and secrets are never part of a
schema, so they can never be stored in an event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

FIELD_TYPES = ("string", "number", "boolean", "uuid", "list")


class TriggerError(ValueError):
    pass


class UnknownTriggerError(TriggerError):
    pass


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str
    label: str
    ref: str | None = None  # brand | user | social_account | project
    choices: tuple[str, ...] | None = None
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "label": self.label,
            "ref": self.ref,
            "choices": list(self.choices) if self.choices else None,
            "description": self.description,
            "operators": list(OPERATORS_BY_TYPE[self.type]),
        }


class ApprovalReminderConfiguration(BaseModel):
    """Trigger configuration for ``APPROVAL_REMINDER_DUE``."""

    model_config = ConfigDict(extra="forbid")

    deadline_hours: int = Field(
        ge=1, le=720, description="Fire once per approval request after it has been pending for this many hours."
    )


class EmptyConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class TriggerSpec:
    type: str
    label: str
    description: str
    category: str
    entity_type: str
    fields: tuple[FieldSpec, ...]
    sample: dict[str, Any]
    configuration_model: type[BaseModel] = EmptyConfiguration
    configuration_fields: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def field_map(self) -> dict[str, FieldSpec]:
        return {item.name: item for item in self.fields}

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "description": self.description,
            "category": self.category,
            "entity_type": self.entity_type,
            "fields": [item.as_dict() for item in self.fields],
            "sample_payload": dict(self.sample),
            "configuration_fields": [dict(item) for item in self.configuration_fields],
        }


# Operators -------------------------------------------------------------------

OPERATORS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "string": ("equals", "not_equals", "in", "not_in", "contains", "not_contains", "is_empty", "is_not_empty"),
    "uuid": ("equals", "not_equals", "in", "not_in", "is_empty", "is_not_empty"),
    "number": ("equals", "not_equals", "greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal", "is_empty", "is_not_empty"),
    "boolean": ("equals",),
    "list": ("contains", "not_contains", "is_empty", "is_not_empty"),
}
VALUELESS_OPERATORS = frozenset({"is_empty", "is_not_empty"})
LIST_VALUE_OPERATORS = frozenset({"in", "not_in"})


# Shared field groups ----------------------------------------------------------

PLATFORMS = ("facebook", "instagram")
ACCOUNT_PLATFORMS = ("facebook_page", "instagram")
CONTENT_STATUSES = ("draft", "ready_for_review", "in_review", "rejected", "approved", "archived")
PUBLICATION_STATUSES = ("pending", "processing", "publishing", "published", "failed", "cancelled")
PUBLISHING_ERROR_CATEGORIES = ("network", "rate_limited", "token_expired", "permission", "invalid_media", "validation", "configuration", "permanent", "uncertain", "temporary")
SYNC_STATUSES = ("pending", "running", "succeeded", "partial", "failed", "cancelled")

_CONTENT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("project_id", "uuid", "Content post", ref="project"),
    FieldSpec("brand_id", "uuid", "Brand", ref="brand"),
    FieldSpec("title", "string", "Title"),
    FieldSpec("content_type", "string", "Content type"),
    FieldSpec("platforms", "list", "Selected platforms", description="Values: facebook, instagram"),
    FieldSpec("status", "string", "Content status", choices=CONTENT_STATUSES),
    FieldSpec("created_by", "uuid", "Created by", ref="user"),
    FieldSpec("assigned_to", "uuid", "Assigned to", ref="user"),
    FieldSpec("actor_user_id", "uuid", "Performed by", ref="user"),
    FieldSpec("labels", "list", "Labels"),
)
_APPROVAL_FIELDS: tuple[FieldSpec, ...] = _CONTENT_FIELDS + (
    FieldSpec("approval_id", "uuid", "Approval request"),
    FieldSpec("decision", "string", "Decision", choices=("pending", "approved", "rejected", "changes_requested")),
    FieldSpec("reviewer_id", "uuid", "Reviewer", ref="user"),
)
_PUBLISHING_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("publication_id", "uuid", "Publishing job"),
    FieldSpec("project_id", "uuid", "Content post", ref="project"),
    FieldSpec("draft_id", "uuid", "Draft"),
    FieldSpec("brand_id", "uuid", "Brand", ref="brand"),
    FieldSpec("platform", "string", "Platform", choices=PLATFORMS),
    FieldSpec("social_account_id", "uuid", "Social account", ref="social_account"),
    FieldSpec("source", "string", "Source", choices=("manual", "schedule")),
    FieldSpec("status", "string", "Publishing status", choices=PUBLICATION_STATUSES),
    FieldSpec("attempt_count", "number", "Attempts made"),
    FieldSpec("max_attempts", "number", "Maximum attempts"),
    FieldSpec("error_category", "string", "Error category", choices=PUBLISHING_ERROR_CATEGORIES),
    FieldSpec("error_code", "string", "Error code"),
    FieldSpec("requires_user_action", "boolean", "Needs user action"),
    FieldSpec("outcome_uncertain", "boolean", "Outcome uncertain"),
    FieldSpec("requested_by", "uuid", "Requested by", ref="user"),
    FieldSpec("scheduled_post_id", "uuid", "Scheduled post"),
    FieldSpec("title", "string", "Title"),
)
_SCHEDULE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("scheduled_post_id", "uuid", "Scheduled post"),
    FieldSpec("project_id", "uuid", "Content post", ref="project"),
    FieldSpec("draft_id", "uuid", "Draft"),
    FieldSpec("brand_id", "uuid", "Brand", ref="brand"),
    FieldSpec("platform", "string", "Platform", choices=PLATFORMS),
    FieldSpec("social_account_id", "uuid", "Social account", ref="social_account"),
    FieldSpec("scheduled_at", "string", "Scheduled time (UTC)"),
    FieldSpec("timezone", "string", "Timezone"),
    FieldSpec("created_by", "uuid", "Scheduled by", ref="user"),
    FieldSpec("title", "string", "Title"),
)
_ANALYTICS_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("sync_job_id", "uuid", "Synchronization job"),
    FieldSpec("social_account_id", "uuid", "Social account", ref="social_account"),
    FieldSpec("brand_id", "uuid", "Brand", ref="brand"),
    FieldSpec("platform", "string", "Account platform", choices=ACCOUNT_PLATFORMS),
    FieldSpec("status", "string", "Job status", choices=SYNC_STATUSES),
    FieldSpec("trigger", "string", "Job trigger", choices=("manual", "scheduled")),
    FieldSpec("attempt_count", "number", "Attempts made"),
    FieldSpec("consecutive_failures", "number", "Consecutive failed jobs"),
    FieldSpec("records_processed", "number", "Records processed"),
    FieldSpec("error_category", "string", "Error category"),
    FieldSpec("error_code", "string", "Error code"),
    FieldSpec("requested_by", "uuid", "Requested by", ref="user"),
)
_ASSIGNMENT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("project_id", "uuid", "Content post", ref="project"),
    FieldSpec("brand_id", "uuid", "Brand", ref="brand"),
    FieldSpec("title", "string", "Title"),
    FieldSpec("status", "string", "Content status", choices=CONTENT_STATUSES),
    FieldSpec("assigned_to", "uuid", "Assigned to", ref="user"),
    FieldSpec("assigned_by", "uuid", "Assigned by", ref="user"),
    FieldSpec("created_by", "uuid", "Created by", ref="user"),
    FieldSpec("platforms", "list", "Selected platforms"),
)
_REMINDER_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("approval_id", "uuid", "Approval request"),
    FieldSpec("project_id", "uuid", "Content post", ref="project"),
    FieldSpec("brand_id", "uuid", "Brand", ref="brand"),
    FieldSpec("title", "string", "Title"),
    FieldSpec("created_by", "uuid", "Created by", ref="user"),
    FieldSpec("assigned_to", "uuid", "Assigned to", ref="user"),
    FieldSpec("pending_hours", "number", "Hours waiting for approval"),
    FieldSpec("submitted_at", "string", "Submitted at (UTC)"),
    FieldSpec("platforms", "list", "Selected platforms"),
)

_U = "00000000-0000-4000-8000-00000000000"
SAMPLE_IDS = {
    "project": f"{_U}1",
    "brand": f"{_U}2",
    "user": f"{_U}3",
    "reviewer": f"{_U}4",
    "approval": f"{_U}5",
    "publication": f"{_U}6",
    "draft": f"{_U}7",
    "account": f"{_U}8",
    "schedule": f"{_U}9",
    "sync": f"{_U}a",
}

_CONTENT_SAMPLE = {
    "project_id": SAMPLE_IDS["project"],
    "brand_id": SAMPLE_IDS["brand"],
    "title": "Spring launch announcement",
    "content_type": "image_post",
    "platforms": ["facebook", "instagram"],
    "status": "draft",
    "created_by": SAMPLE_IDS["user"],
    "assigned_to": None,
    "actor_user_id": SAMPLE_IDS["user"],
    "labels": [],
}
_PUBLISHING_SAMPLE = {
    "publication_id": SAMPLE_IDS["publication"],
    "project_id": SAMPLE_IDS["project"],
    "draft_id": SAMPLE_IDS["draft"],
    "brand_id": SAMPLE_IDS["brand"],
    "platform": "facebook",
    "social_account_id": SAMPLE_IDS["account"],
    "source": "schedule",
    "status": "failed",
    "attempt_count": 3,
    "max_attempts": 3,
    "error_category": "token_expired",
    "error_code": "190",
    "requires_user_action": True,
    "outcome_uncertain": False,
    "requested_by": SAMPLE_IDS["user"],
    "scheduled_post_id": SAMPLE_IDS["schedule"],
    "title": "Spring launch announcement",
}
_ANALYTICS_SAMPLE = {
    "sync_job_id": SAMPLE_IDS["sync"],
    "social_account_id": SAMPLE_IDS["account"],
    "brand_id": SAMPLE_IDS["brand"],
    "platform": "facebook_page",
    "status": "failed",
    "trigger": "scheduled",
    "attempt_count": 3,
    "consecutive_failures": 2,
    "records_processed": 0,
    "error_category": "token_expired",
    "error_code": "190",
    "requested_by": None,
}


def _content(type_: str, label: str, description: str, *, status: str, **extra: Any) -> TriggerSpec:
    sample = {**_CONTENT_SAMPLE, "status": status, **extra}
    return TriggerSpec(type_, label, description, "content", "content_project", _CONTENT_FIELDS, sample)


def _approval(type_: str, label: str, description: str, *, status: str, decision: str) -> TriggerSpec:
    sample = {
        **_CONTENT_SAMPLE,
        "status": status,
        "approval_id": SAMPLE_IDS["approval"],
        "decision": decision,
        "reviewer_id": SAMPLE_IDS["reviewer"] if decision != "pending" else None,
    }
    return TriggerSpec(type_, label, description, "content", "content_project", _APPROVAL_FIELDS, sample)


def _publishing(type_: str, label: str, description: str, *, status: str, **extra: Any) -> TriggerSpec:
    sample = {**_PUBLISHING_SAMPLE, "status": status, **extra}
    return TriggerSpec(type_, label, description, "publishing", "content_publication", _PUBLISHING_FIELDS, sample)


TRIGGERS: dict[str, TriggerSpec] = {
    spec.type: spec
    for spec in (
        _content("CONTENT_CREATED", "Content created", "A content post was created.", status="draft"),
        _approval(
            "CONTENT_SUBMITTED_FOR_APPROVAL",
            "Content submitted for approval",
            "A content post was submitted for review.",
            status="ready_for_review",
            decision="pending",
        ),
        _approval("CONTENT_APPROVED", "Content approved", "A reviewer approved a content post.", status="approved", decision="approved"),
        _approval(
            "CONTENT_REJECTED",
            "Content rejected or changes requested",
            "A reviewer rejected a content post or requested changes (see the decision field).",
            status="rejected",
            decision="rejected",
        ),
        _content("CONTENT_UPDATED", "Content updated", "A content post or one of its drafts was edited.", status="draft"),
        TriggerSpec(
            "POST_SCHEDULED",
            "Post scheduled",
            "An approved draft was scheduled for publication.",
            "publishing",
            "scheduled_post",
            _SCHEDULE_FIELDS,
            {
                "scheduled_post_id": SAMPLE_IDS["schedule"],
                "project_id": SAMPLE_IDS["project"],
                "draft_id": SAMPLE_IDS["draft"],
                "brand_id": SAMPLE_IDS["brand"],
                "platform": "instagram",
                "social_account_id": SAMPLE_IDS["account"],
                "scheduled_at": "2026-12-01T09:00:00Z",
                "timezone": "UTC",
                "created_by": SAMPLE_IDS["user"],
                "title": "Spring launch announcement",
            },
        ),
        _publishing("POST_PUBLISHING", "Post publishing started", "A worker started a publishing attempt.", status="processing", attempt_count=1, error_category=None, error_code=None, requires_user_action=False),
        _publishing("POST_PUBLISHED", "Post published", "A post was published successfully.", status="published", error_category=None, error_code=None, requires_user_action=False),
        _publishing("POST_PUBLISH_FAILED", "Post publishing failed", "A publishing job failed after its last attempt or needs user action.", status="failed"),
        _publishing("POST_CANCELLED", "Post cancelled", "A pending publishing job was cancelled.", status="cancelled", error_category=None, error_code=None, requires_user_action=False),
        TriggerSpec(
            "ANALYTICS_SYNC_COMPLETED",
            "Analytics synchronization completed",
            "An analytics synchronization finished (fully or partially).",
            "analytics",
            "analytics_sync_job",
            _ANALYTICS_FIELDS,
            {**_ANALYTICS_SAMPLE, "status": "succeeded", "consecutive_failures": 0, "records_processed": 42, "error_category": None, "error_code": None},
        ),
        TriggerSpec(
            "ANALYTICS_SYNC_FAILED",
            "Analytics synchronization failed",
            "An analytics synchronization failed after its last attempt.",
            "analytics",
            "analytics_sync_job",
            _ANALYTICS_FIELDS,
            _ANALYTICS_SAMPLE,
        ),
        TriggerSpec(
            "TEAM_MEMBER_ASSIGNED",
            "Team member assigned",
            "A content post was assigned to a workspace member.",
            "team",
            "content_project",
            _ASSIGNMENT_FIELDS,
            {
                "project_id": SAMPLE_IDS["project"],
                "brand_id": SAMPLE_IDS["brand"],
                "title": "Spring launch announcement",
                "status": "draft",
                "assigned_to": SAMPLE_IDS["reviewer"],
                "assigned_by": SAMPLE_IDS["user"],
                "created_by": SAMPLE_IDS["user"],
                "platforms": ["facebook"],
            },
        ),
        TriggerSpec(
            "APPROVAL_REMINDER_DUE",
            "Approval reminder due",
            "A content post has been waiting for approval longer than the configured deadline.",
            "team",
            "content_approval",
            _REMINDER_FIELDS,
            {
                "approval_id": SAMPLE_IDS["approval"],
                "project_id": SAMPLE_IDS["project"],
                "brand_id": SAMPLE_IDS["brand"],
                "title": "Spring launch announcement",
                "created_by": SAMPLE_IDS["user"],
                "assigned_to": None,
                "pending_hours": 26,
                "submitted_at": "2026-11-10T08:00:00Z",
                "platforms": ["facebook", "instagram"],
            },
            ApprovalReminderConfiguration,
            (
                {
                    "name": "deadline_hours",
                    "type": "number",
                    "label": "Deadline (hours)",
                    "required": True,
                    "min": 1,
                    "max": 720,
                    "description": "Fire once per approval request after it has waited this many hours.",
                },
            ),
        ),
    )
}


def get_trigger(event_type: str) -> TriggerSpec:
    spec = TRIGGERS.get(event_type)
    if spec is None:
        raise UnknownTriggerError(f"Unknown trigger: {event_type}")
    return spec


def list_triggers() -> list[dict[str, Any]]:
    return [spec.as_dict() for spec in TRIGGERS.values()]


def validate_trigger_configuration(spec: TriggerSpec, configuration: dict[str, Any] | None) -> dict[str, Any]:
    try:
        return spec.configuration_model.model_validate(configuration or {}).model_dump()
    except Exception as exc:  # pydantic.ValidationError
        raise TriggerError(f"Invalid trigger configuration: {_pydantic_summary(exc)}") from exc


def _pydantic_summary(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        parts = []
        for item in errors():
            location = ".".join(str(part) for part in item.get("loc", ()))
            parts.append(f"{location}: {item.get('msg')}" if location else str(item.get("msg")))
        return "; ".join(parts)
    return str(exc)


# Payload normalization --------------------------------------------------------


def _coerce(field_spec: FieldSpec, value: Any) -> Any:
    if value is None:
        return None
    try:
        if field_spec.type == "uuid":
            if isinstance(value, UUID):
                return str(value)
            return str(UUID(str(value)))
        if field_spec.type == "string":
            text = value if isinstance(value, str) else str(value)
            return text[:500]
        if field_spec.type == "number":
            if isinstance(value, bool):
                return None
            number = float(value)
            return int(number) if number.is_integer() else number
        if field_spec.type == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.casefold() in {"true", "1", "yes"}
            return bool(value)
        if field_spec.type == "list":
            if isinstance(value, (list, tuple, set)):
                return [str(item)[:200] for item in list(value)[:100]]
            return None
    except (TypeError, ValueError):
        return None
    return None


def normalize_payload(spec: TriggerSpec, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only documented fields, coerced to their declared type."""
    payload = payload or {}
    normalized: dict[str, Any] = {}
    for field_spec in spec.fields:
        normalized[field_spec.name] = _coerce(field_spec, payload.get(field_spec.name))
    return normalized


def payload_errors(spec: TriggerSpec, payload: dict[str, Any]) -> list[str]:
    """Report values that do not fit the schema (used by validation endpoints)."""
    errors: list[str] = []
    known = spec.field_map()
    for key, value in payload.items():
        if key not in known:
            errors.append(f"Unknown field '{key}' for trigger {spec.type}.")
            continue
        if value is not None and _coerce(known[key], value) is None:
            errors.append(f"Field '{key}' must be of type {known[key].type}.")
    return errors
