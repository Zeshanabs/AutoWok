"""Phase 11: multi-agent workflow persistence.

Agent definitions live in code (``app.services.agents.registry``); the database
stores only per-workspace switches and what is needed to run, audit and recover
a workflow. No API keys or provider secrets are stored in these tables.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.user import utc_now

WORKFLOW_STATUSES = ("pending", "running", "succeeded", "failed", "cancelled")
ACTIVE_WORKFLOW_STATUSES = ("pending", "running")
STEP_STATUSES = ("pending", "running", "succeeded", "failed", "skipped", "cancelled")
EXECUTION_STATUSES = ("running", "succeeded", "failed", "cancelled")
REVIEW_STATUSES = ("pending", "accepted", "rejected")


class AgentSetting(Base):
    """Workspace switch for one registered agent (absent row = enabled)."""

    __tablename__ = "agent_settings"
    __table_args__ = (UniqueConstraint("workspace_id", "agent_key", name="uq_agent_setting_workspace_agent"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_key: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    updated_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AgentWorkflow(Base):
    """One run of a predefined multi-agent workflow."""

    __tablename__ = "agent_workflows"
    __table_args__ = (
        Index("ix_agent_workflows_workspace_created", "workspace_id", "created_at"),
        Index("ix_agent_workflows_due", "status", "next_attempt_at"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_agent_workflow_status",
        ),
        CheckConstraint(
            "review_status IS NULL OR review_status IN ('pending', 'accepted', 'rejected')",
            name="ck_agent_workflow_review_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL"), nullable=True
    )
    workflow_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    input_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    final_output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(default=False, nullable=False)
    agent_call_count: Mapped[int] = mapped_column(default=0, nullable=False)
    revision_count: Mapped[int] = mapped_column(default=0, nullable=False)
    auto_revision_count: Mapped[int] = mapped_column(default=0, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(120))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Human review of the final output. Agents never set "accepted".
    review_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_project_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_projects.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    steps: Mapped[list[AgentWorkflowStep]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="AgentWorkflowStep.step_order"
    )
    executions: Mapped[list[AgentExecution]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="AgentExecution.started_at"
    )
    messages: Mapped[list[AgentMessage]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="AgentMessage.created_at"
    )


class AgentWorkflowStep(Base):
    """One planned step. ``step_key`` is ``base_key`` plus a revision suffix (``writer:r1``)."""

    __tablename__ = "agent_workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_id", "step_key", name="uq_agent_step_key"),
        UniqueConstraint("workflow_id", "step_order", name="uq_agent_step_order"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'skipped', 'cancelled')",
            name="ck_agent_step_status",
        ),
        CheckConstraint("kind IN ('context', 'agent', 'compile')", name="ck_agent_step_kind"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(nullable=False)
    step_key: Mapped[str] = mapped_column(String(80), nullable=False)
    base_key: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_round: Mapped[int] = mapped_column(default=0, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    agent_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    # {"depends_on": [step keys], "parallel_group": str | None, "feedback": str | None}
    dependency_configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    execution_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    workflow: Mapped[AgentWorkflow] = relationship(back_populates="steps")


class AgentExecution(Base):
    """One attempt of one step. ``output_data`` is the structured agent response envelope."""

    __tablename__ = "agent_executions"
    __table_args__ = (
        Index("ix_agent_executions_workflow_started", "workflow_id", "started_at"),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'cancelled')",
            name="ck_agent_execution_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_workflow_steps.id", ondelete="SET NULL"), nullable=True, index=True
    )
    step_key: Mapped[str] = mapped_column(String(80), nullable=False)
    agent_key: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_version: Mapped[str | None] = mapped_column(String(20))
    attempt_number: Mapped[int] = mapped_column(default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    input_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120))
    # {"prompt_tokens": int | None, "completion_tokens": int | None, "total_tokens": int | None}
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    execution_duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workflow: Mapped[AgentWorkflow] = relationship(back_populates="executions")


class AgentMessage(Base):
    """Structured message between the orchestrator and an agent (audit trail, not a chat log)."""

    __tablename__ = "agent_messages"
    __table_args__ = (Index("ix_agent_messages_workflow_created", "workflow_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_agent: Mapped[str] = mapped_column(String(64), nullable=False)
    receiver_agent: Mapped[str] = mapped_column(String(64), nullable=False)
    message_type: Mapped[str] = mapped_column(String(32), nullable=False)
    structured_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    workflow: Mapped[AgentWorkflow] = relationship(back_populates="messages")
