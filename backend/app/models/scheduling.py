"""Phase 8: scheduled publishing and its audit trail.

A ``ScheduledPost`` says *when* a draft should go to an account. At the due
time the scheduler creates a normal Phase 7 publishing job
(``ContentPublication``) and links it, so all Meta publishing, attempts,
retries, and duplicate protection stay in one place.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.user import utc_now

SCHEDULE_STATUSES = ("scheduled", "queued", "processing", "published", "failed", "cancelled")
ACTIVE_SCHEDULE_STATUSES = ("scheduled", "queued", "processing")


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"
    __table_args__ = (
        Index("ix_scheduled_posts_due", "status", "scheduled_at"),
        Index("ix_scheduled_posts_workspace_time", "workspace_id", "scheduled_at"),
        UniqueConstraint("active_guard", name="uq_scheduled_post_active_guard"),
        CheckConstraint(
            "status IN ('scheduled', 'queued', 'processing', 'published', 'failed', 'cancelled')",
            name="ck_scheduled_post_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    draft_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_drafts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    social_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL"), nullable=True, index=True
    )
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    # Authoritative instant (UTC). ``scheduled_local`` + ``timezone`` keep the
    # wall-clock time the user chose, for display and DST-aware editing.
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_local: Mapped[str] = mapped_column(String(19), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="scheduled", nullable=False)
    # Incremented on every reschedule/update; the scheduler only claims the
    # revision it read, so stale work can never publish an old schedule.
    revision: Mapped[int] = mapped_column(default=1, nullable=False)
    content_version_number: Mapped[int] = mapped_column(nullable=False)
    # Set while active or published: one schedule per draft and account.
    active_guard: Mapped[str | None] = mapped_column(String(120), nullable=True)
    publication_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_publications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    history: Mapped[list[SchedulingHistory]] = relationship(
        back_populates="scheduled_post",
        cascade="all, delete-orphan",
        order_by="SchedulingHistory.created_at",
    )


class SchedulingHistory(Base):
    __tablename__ = "scheduling_history"
    __table_args__ = (Index("ix_scheduling_history_post_created", "scheduled_post_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    scheduled_post_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("scheduled_posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    previous_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    performed_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    scheduled_post: Mapped[ScheduledPost] = relationship(back_populates="history")
