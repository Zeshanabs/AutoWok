"""Phase 10: controlled workflow automations.

An ``Automation`` is a rule: *trigger* (an event type the application emits),
*conditions* (a validated JSON structure) and ordered *actions* (allowlisted
``AutomationAction`` rows). Business code persists ``AutomationEvent`` rows in
the same transaction as the change they describe (outbox pattern). The worker
dispatches events to matching automations, creating ``AutomationExecution``
rows (one per automation and event, enforced by a unique idempotency key),
then runs each execution step by step (``AutomationExecutionStep``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.user import utc_now

AUTOMATION_STATUSES = ("draft", "enabled", "paused", "archived")
EVENT_STATUSES = ("pending", "processing", "processed", "failed")
EXECUTION_STATUSES = ("pending", "running", "succeeded", "failed", "cancelled")
ACTIVE_EXECUTION_STATUSES = ("pending", "running")
STEP_STATUSES = ("pending", "running", "succeeded", "failed", "skipped")


class Automation(Base):
    __tablename__ = "automations"
    __table_args__ = (
        Index("ix_automations_workspace_status", "workspace_id", "status"),
        Index("ix_automations_workspace_trigger", "workspace_id", "trigger_type", "status"),
        CheckConstraint("status IN ('draft', 'enabled', 'paused', 'archived')", name="ck_automation_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    conditions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # Optional lifetime cap and minimum spacing between executions (seconds).
    max_executions: Mapped[int | None] = mapped_column(nullable=True)
    cooldown_seconds: Mapped[int] = mapped_column(default=0, nullable=False)
    execution_count: Mapped[int] = mapped_column(default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_dry_run: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    last_dry_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    actions: Mapped[list[AutomationAction]] = relationship(
        back_populates="automation", cascade="all, delete-orphan", order_by="AutomationAction.execution_order"
    )
    executions: Mapped[list[AutomationExecution]] = relationship(
        back_populates="automation", cascade="all, delete-orphan"
    )


class AutomationAction(Base):
    __tablename__ = "automation_actions"
    __table_args__ = (
        UniqueConstraint("automation_id", "execution_order", name="uq_automation_action_order"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    automation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("automations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    action_configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    execution_order: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    automation: Mapped[Automation] = relationship(back_populates="actions")


class AutomationEvent(Base):
    """A persisted trigger event (outbox). ``dedupe_key`` makes delivery idempotent."""

    __tablename__ = "automation_events"
    __table_args__ = (
        Index("ix_automation_events_due", "status", "next_attempt_at"),
        Index("ix_automation_events_workspace_occurred", "workspace_id", "occurred_at"),
        Index("ix_automation_events_type_occurred", "workspace_id", "event_type", "occurred_at"),
        UniqueConstraint("dedupe_key", name="uq_automation_event_dedupe"),
        CheckConstraint("status IN ('pending', 'processing', 'processed', 'failed')", name="ck_automation_event_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_entity_type: Mapped[str | None] = mapped_column(String(64))
    source_entity_id: Mapped[str | None] = mapped_column(String(64))
    # Only fields of the trigger's documented schema; never tokens or secrets.
    event_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(120))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Loop prevention: set when the event was caused by an automation action.
    origin_automation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("automations.id", ondelete="SET NULL"), nullable=True
    )
    origin_execution_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    chain_depth: Mapped[int] = mapped_column(default=0, nullable=False)
    # Per-automation outcome of dispatching this event (matched, skipped and why).
    dispatch_summary: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AutomationExecution(Base):
    __tablename__ = "automation_executions"
    __table_args__ = (
        Index("ix_automation_executions_automation_created", "automation_id", "created_at"),
        Index("ix_automation_executions_workspace_created", "workspace_id", "created_at"),
        Index("ix_automation_executions_due", "status", "next_attempt_at"),
        UniqueConstraint("idempotency_key", name="uq_automation_execution_idempotency"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_automation_execution_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    automation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("automations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger_event_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("automation_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Snapshot of the normalized payload and the condition results that matched.
    execution_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(default=3, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(120))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chain_depth: Mapped[int] = mapped_column(default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    retried_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    automation: Mapped[Automation] = relationship(back_populates="executions")
    steps: Mapped[list[AutomationExecutionStep]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", order_by="AutomationExecutionStep.execution_order"
    )


class AutomationExecutionStep(Base):
    __tablename__ = "automation_execution_steps"
    __table_args__ = (
        UniqueConstraint("execution_id", "execution_order", name="uq_automation_step_order"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')",
            name="ck_automation_step_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    execution_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("automation_executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("automation_actions.id", ondelete="SET NULL"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_order: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    execution: Mapped[AutomationExecution] = relationship(back_populates="steps")


class Notification(Base):
    """In-app notification for one workspace member."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_workspace_created", "user_id", "workspace_id", "created_at"),
        Index("ix_notifications_user_unread", "user_id", "read_at"),
        UniqueConstraint("dedupe_key", name="uq_notification_dedupe"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    automation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("automations.id", ondelete="SET NULL"), nullable=True
    )
    execution_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("automation_executions.id", ondelete="SET NULL"), nullable=True
    )
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


TASK_KINDS = ("task", "followup", "reminder", "incident", "analytics_followup")
TASK_STATUSES = ("open", "done")


class ContentTask(Base):
    """Internal work item created by automations (follow-ups, reminders, incidents)."""

    __tablename__ = "content_tasks"
    __table_args__ = (
        Index("ix_content_tasks_workspace_status_created", "workspace_id", "status", "created_at"),
        Index("ix_content_tasks_assignee_status", "assigned_to", "status"),
        UniqueConstraint("dedupe_key", name="uq_content_task_dedupe"),
        CheckConstraint("status IN ('open', 'done')", name="ck_content_task_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    publication_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_publications.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), default="task", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    assigned_to: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    automation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("automations.id", ondelete="SET NULL"), nullable=True
    )
    execution_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("automation_executions.id", ondelete="SET NULL"), nullable=True
    )
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
