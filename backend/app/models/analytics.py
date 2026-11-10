"""Phase 9: social media analytics storage.

Three kinds of records are kept, all scoped to a workspace:

* ``AnalyticsSnapshot`` - one normalized account-level metric value for one
  calendar day (for example Instagram ``reach`` on 2026-11-08). The source
  metric name, unit and collection time are stored with every value so the
  user can see *what* was measured and *when* it was retrieved.
* ``PostAnalytics`` - the latest known metrics for one published post on one
  account, plus ``PostAnalyticsHistory`` rows (one per collection day) so
  performance can be tracked over time.
* ``AnalyticsSyncJob`` - the synchronization record for one account run,
  including retries, errors and how many records were processed.

Facebook and Instagram values are never merged in storage: every row carries
its platform and its platform-specific source metric name.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.user import utc_now

ANALYTICS_PLATFORMS = ("facebook_page", "instagram")
SYNC_STATUSES = ("pending", "running", "succeeded", "partial", "failed", "cancelled")
ACTIVE_SYNC_STATUSES = ("pending", "running")
SYNC_TRIGGERS = ("manual", "scheduled")


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "social_account_id",
            "metric_key",
            "period",
            "snapshot_date",
            name="uq_analytics_snapshot_account_metric_day",
        ),
        Index("ix_analytics_snapshots_workspace_date", "workspace_id", "snapshot_date"),
        Index("ix_analytics_snapshots_account_metric", "social_account_id", "metric_key", "snapshot_date"),
        CheckConstraint("platform IN ('facebook_page', 'instagram')", name="ck_analytics_snapshot_platform"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL"), nullable=True, index=True
    )
    social_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    # Normalized metric key (see app.services.analytics.metrics) and the exact
    # Meta metric or object field it came from.
    metric_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_metric: Mapped[str] = mapped_column(String(128), nullable=False)
    period: Mapped[str] = mapped_column(String(16), default="day", nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    metric_unit: Mapped[str] = mapped_column(String(32), default="count", nullable=False)
    # Breakdown dictionaries from Meta (e.g. reactions by type), kept verbatim.
    value_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="meta_graph", nullable=False)
    api_version: Mapped[str | None] = mapped_column(String(16))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class PostAnalytics(Base):
    __tablename__ = "post_analytics"
    __table_args__ = (
        UniqueConstraint("social_account_id", "external_post_id", name="uq_post_analytics_account_post"),
        Index("ix_post_analytics_workspace_published", "workspace_id", "published_at"),
        Index("ix_post_analytics_publication", "publication_id"),
        CheckConstraint("platform IN ('facebook_page', 'instagram')", name="ck_post_analytics_platform"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL"), nullable=True, index=True
    )
    social_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    # Link to the Autowok content that produced the post (None for posts
    # published outside Autowok).
    publication_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_publications.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    draft_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_drafts.id", ondelete="SET NULL"), nullable=True
    )
    external_post_id: Mapped[str] = mapped_column(String(255), nullable=False)
    permalink: Mapped[str | None] = mapped_column(String(2048))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # Platform content format (facebook: text/photo/multi_photo/video/link/other;
    # instagram: image/carousel/reel/video).
    content_format: Mapped[str | None] = mapped_column(String(40))
    caption_preview: Mapped[str | None] = mapped_column(String(280))
    thumbnail_url: Mapped[str | None] = mapped_column(String(2048))
    # Normalized metrics. ``None`` always means "not available", never zero.
    reach: Mapped[int | None] = mapped_column(nullable=True)
    views: Mapped[int | None] = mapped_column(nullable=True)
    engagements: Mapped[int | None] = mapped_column(nullable=True)
    likes: Mapped[int | None] = mapped_column(nullable=True)
    reactions: Mapped[int | None] = mapped_column(nullable=True)
    comments: Mapped[int | None] = mapped_column(nullable=True)
    shares: Mapped[int | None] = mapped_column(nullable=True)
    saves: Mapped[int | None] = mapped_column(nullable=True)
    clicks: Mapped[int | None] = mapped_column(nullable=True)
    video_views: Mapped[int | None] = mapped_column(nullable=True)
    # Raw Meta values keyed by source metric/field name, plus availability
    # notes per normalized key ({"saves": "not_supported_on_platform", ...}).
    raw_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    metric_availability: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="meta_graph", nullable=False)
    api_version: Mapped[str | None] = mapped_column(String(16))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    history: Mapped[list[PostAnalyticsHistory]] = relationship(
        back_populates="post", cascade="all, delete-orphan", order_by="PostAnalyticsHistory.snapshot_date"
    )


class PostAnalyticsHistory(Base):
    """One normalized metric set per post per collection day (for trends)."""

    __tablename__ = "post_analytics_history"
    __table_args__ = (
        UniqueConstraint("post_analytics_id", "snapshot_date", name="uq_post_analytics_history_day"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    post_analytics_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("post_analytics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    post: Mapped[PostAnalytics] = relationship(back_populates="history")


class AnalyticsSyncJob(Base):
    __tablename__ = "analytics_sync_jobs"
    __table_args__ = (
        Index("ix_analytics_sync_jobs_due", "status", "next_attempt_at"),
        Index("ix_analytics_sync_jobs_account_created", "social_account_id", "created_at"),
        # Set while pending/running so the database enforces one active job per account.
        UniqueConstraint("active_guard", name="uq_analytics_sync_job_active_guard"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'partial', 'failed', 'cancelled')",
            name="ck_analytics_sync_job_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    social_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), default="scheduled", nullable=False)
    requested_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    active_guard: Mapped[str | None] = mapped_column(String(80), nullable=True)
    range_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    range_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(default=3, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(120))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_category: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(Text)
    records_processed: Mapped[int] = mapped_column(default=0, nullable=False)
    # Counters and per-metric availability notes (credential-free).
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
