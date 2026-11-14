from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

WorkflowType = Literal["content_research", "social_content", "content_repurposing", "performance_analysis"]


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid", protected_namespaces=())


# Requests -------------------------------------------------------------------------


class WorkflowStartRequest(APIModel):
    workflow_type: WorkflowType
    task: str = Field(min_length=3, max_length=2000)
    name: str | None = Field(default=None, max_length=200)
    brand_id: UUID | None = None
    research_ids: list[UUID] = Field(default_factory=list, max_length=5)
    content_project_id: UUID | None = None
    platforms: list[Literal["facebook", "instagram"]] = Field(default_factory=lambda: ["facebook", "instagram"], min_length=1, max_length=2)
    days: int = Field(default=30, ge=7, le=90)
    run_new_research: bool = False

    @field_validator("task")
    @classmethod
    def clean_task(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 3:
            raise ValueError("Describe the task in at least a few words.")
        return cleaned


class AgentUpdateRequest(APIModel):
    enabled: bool


class AcceptRequest(APIModel):
    idea_index: int | None = Field(default=None, ge=0, le=20)


class ReviseRequest(APIModel):
    feedback: str = Field(min_length=3, max_length=1000)


class RejectRequest(APIModel):
    reason: str | None = Field(default=None, max_length=1000)


# Responses ------------------------------------------------------------------------


class AgentRead(APIModel):
    key: str
    name: str
    description: str
    responsibility: str
    version: str
    enabled: bool
    required_role: str
    tools: list[dict[str, str]]
    model: dict[str, Any]
    limits: dict[str, Any]
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None


class PlannedStepRead(APIModel):
    step_order: int
    step_key: str
    base_key: str
    kind: str
    agent_key: str
    agent_name: str
    label: str
    depends_on: list[str]
    parallel_group: str | None = None


class WorkflowDefinitionRead(APIModel):
    key: str
    name: str
    description: str
    deliverables: list[str]
    requires: list[str]
    optional: list[str]
    agents: list[str]
    supports_revision: bool
    accept_mode: str | None
    steps: list[PlannedStepRead]
    disabled_agents: list[str] = Field(default_factory=list)


class CatalogRead(APIModel):
    workflows: list[WorkflowDefinitionRead]
    agents: list[AgentRead]
    limits: dict[str, Any]
    groq: dict[str, Any]


class PlanRead(APIModel):
    workflow: WorkflowDefinitionRead
    input_data: dict[str, Any]
    estimated_agent_calls: int
    notes: list[str]


class ExecutionRead(APIModel):
    id: UUID
    step_key: str
    agent_key: str
    agent_version: str | None
    attempt_number: int
    status: str
    model_name: str | None
    token_usage: dict[str, Any] | None
    execution_duration_ms: int | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    warnings: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    input_data: dict[str, Any] | None = None


class StepRead(APIModel):
    id: UUID
    step_order: int
    step_key: str
    base_key: str
    revision_round: int
    kind: str
    agent_key: str
    agent_name: str
    label: str
    depends_on: list[str]
    parallel_group: str | None
    status: str
    attempt_count: int
    error_message: str | None
    execution: ExecutionRead | None = None


class WorkflowRead(APIModel):
    id: UUID
    workspace_id: UUID
    brand_id: UUID | None
    brand_name: str | None
    workflow_type: str
    workflow_name: str
    name: str
    task: str
    status: str
    error_message: str | None
    cancel_requested: bool
    agent_call_count: int
    revision_count: int
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    review_status: str | None
    review_note: str | None
    accepted_project_id: UUID | None
    created_by: UUID | None
    created_by_name: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    next_attempt_at: datetime | None
    steps_total: int
    steps_done: int
    can_cancel: bool
    can_accept: bool
    can_revise: bool
    can_reject: bool
    supports_revision: bool
    accept_mode: str | None


class WorkflowDetailRead(WorkflowRead):
    input_data: dict[str, Any]
    agents: list[str]
    steps: list[StepRead]
    final_output: dict[str, Any] | None
    messages: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowListRead(APIModel):
    items: list[WorkflowRead]
    total: int
    offset: int
    limit: int


class StatsRead(APIModel):
    days: int
    counts: dict[str, int]
    total: int
    active: int
    agent_calls: int
    total_tokens: int
    limits: dict[str, Any]
    recent: list[WorkflowRead]


class AcceptRead(APIModel):
    project_id: UUID
    draft_ids: dict[str, str]
    status: str
    workflow: WorkflowRead
