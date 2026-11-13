from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


# Definitions -------------------------------------------------------------------


class ActionInput(APIModel):
    action_type: str = Field(min_length=1, max_length=64)
    configuration: dict[str, Any] = Field(default_factory=dict)


class AutomationDefinition(APIModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    brand_id: UUID | None = None
    trigger_type: str = Field(min_length=1, max_length=64)
    trigger_configuration: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Any] | list[Any] | None = None
    actions: list[ActionInput] = Field(default_factory=list, max_length=50)
    max_executions: int | None = Field(default=None, ge=1, le=1_000_000)
    cooldown_seconds: int = Field(default=0, ge=0, le=86400)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Automation name must contain at least two characters.")
        return normalized


class AutomationCreate(AutomationDefinition):
    pass


class AutomationUpdate(APIModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    brand_id: UUID | None = None
    trigger_type: str | None = Field(default=None, min_length=1, max_length=64)
    trigger_configuration: dict[str, Any] | None = None
    conditions: dict[str, Any] | list[Any] | None = None
    actions: list[ActionInput] | None = Field(default=None, max_length=50)
    max_executions: int | None = Field(default=None, ge=1, le=1_000_000)
    cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)
    clear_brand: bool = False
    clear_max_executions: bool = False


class ValidationRead(APIModel):
    valid: bool
    errors: list[str]
    warnings: list[str]


class DryRunRequest(APIModel):
    payload_source: Literal["sample", "latest_event"] = "sample"
    payload_overrides: dict[str, Any] | None = None


class DryRunDefinitionRequest(DryRunRequest):
    automation: AutomationDefinition


class DryRunActionRead(APIModel):
    order: int
    action_type: str
    label: str
    status: Literal["would_run", "blocked"]
    detail: str
    errors: list[str]


class DryRunRead(APIModel):
    simulated: Literal[True] = True
    generated_at: datetime
    trigger_type: str
    payload_source: str
    event_id: UUID | None
    payload: dict[str, Any]
    conditions_passed: bool
    condition_results: dict[str, Any]
    would_execute: bool
    actions: list[DryRunActionRead]
    errors: list[str]
    notice: str


# Reads -------------------------------------------------------------------------


class AutomationActionRead(APIModel):
    id: UUID
    action_type: str
    label: str
    action_configuration: dict[str, Any]
    execution_order: int


class ExecutionStepRead(APIModel):
    id: UUID
    action_type: str
    execution_order: int
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    result_summary: dict[str, Any] | None
    error_message: str | None


class ExecutionRead(APIModel):
    id: UUID
    automation_id: UUID
    automation_name: str | None
    workspace_id: UUID
    trigger_event_id: UUID | None
    trigger_type: str
    status: str
    retry_count: int
    max_retries: int
    next_attempt_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    chain_depth: int
    created_at: datetime
    can_retry: bool
    execution_context: dict[str, Any] = Field(default_factory=dict)
    steps: list[ExecutionStepRead] = Field(default_factory=list)


class AutomationRead(APIModel):
    id: UUID
    workspace_id: UUID
    brand_id: UUID | None
    brand_name: str | None
    name: str
    description: str | None
    status: str
    trigger_type: str
    trigger_label: str
    trigger_configuration: dict[str, Any]
    conditions: dict[str, Any]
    max_executions: int | None
    cooldown_seconds: int
    execution_count: int
    success_count: int
    failure_count: int
    last_executed_at: datetime | None
    last_execution: ExecutionRead | None
    created_by: UUID | None
    created_by_name: str | None
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime
    enabled_at: datetime | None
    paused_at: datetime | None
    archived_at: datetime | None
    actions: list[AutomationActionRead]
    issues: list[str]
    can_enable: bool


class AutomationDetailRead(AutomationRead):
    recent_executions: list[ExecutionRead]
    last_dry_run: dict[str, Any] | None
    last_dry_run_at: datetime | None


class CatalogRead(APIModel):
    triggers: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    limits: dict[str, Any]


# Notifications and tasks --------------------------------------------------------


class NotificationRead(APIModel):
    id: UUID
    workspace_id: UUID
    category: str
    title: str
    message: str
    resource_type: str | None
    resource_id: str | None
    automation_id: UUID | None
    execution_id: UUID | None
    read_at: datetime | None
    created_at: datetime


class NotificationListRead(APIModel):
    items: list[NotificationRead]
    unread_count: int


class NotificationBulkRead(APIModel):
    notification_ids: list[UUID] | None = Field(default=None, max_length=200)


class TaskRead(APIModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID | None
    project_title: str | None
    publication_id: UUID | None
    kind: str
    title: str
    description: str | None
    severity: str | None
    status: str
    assigned_to: UUID | None
    assigned_to_name: str | None
    due_at: datetime | None
    completed_at: datetime | None
    automation_id: UUID | None
    execution_id: UUID | None
    created_at: datetime
