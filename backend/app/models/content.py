from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.user import utc_now


class ContentProject(Base):
    __tablename__ = "content_projects"
    __table_args__ = (
        Index("ix_content_projects_workspace_status", "workspace_id", "status"),
        Index("ix_content_projects_brand_created", "brand_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    topic: Mapped[str | None] = mapped_column(Text)
    objective: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(80), default="text_post", nullable=False)
    selected_platforms: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    content_pillar: Mapped[str | None] = mapped_column(String(160))
    target_audience: Mapped[str | None] = mapped_column(String(200))
    preferred_tone: Mapped[str | None] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(String(20), default="en", nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    required_phrases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    prohibited_phrases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    cta_requirements: Mapped[str | None] = mapped_column(Text)
    hashtag_preferences: Mapped[str | None] = mapped_column(Text)
    emoji_preferences: Mapped[str | None] = mapped_column(Text)
    desired_length: Mapped[str | None] = mapped_column(String(40))
    research_report_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("research_reports.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    # Phase 10: internal workflow metadata (not part of the published content).
    assigned_to: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    labels: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    drafts: Mapped[list[ContentDraft]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    approvals: Mapped[list[ContentApproval]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ContentDraft(Base):
    __tablename__ = "content_drafts"
    __table_args__ = (
        Index("ix_content_drafts_project_status", "project_id", "status"),
        Index("ix_content_drafts_platform", "project_id", "platform"),
        UniqueConstraint("project_id", "platform", name="uq_content_draft_project_platform"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    hook: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    cta: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    media_asset_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    ai_generated: Mapped[bool] = mapped_column(default=False, nullable=False)
    version_count: Mapped[int] = mapped_column(default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped[ContentProject] = relationship(back_populates="drafts")
    versions: Mapped[list[ContentVersion]] = relationship(
        back_populates="draft", cascade="all, delete-orphan"
    )
    approvals: Mapped[list[ContentApproval]] = relationship(
        back_populates="draft", cascade="all, delete-orphan"
    )


PUBLICATION_STATUSES = ("pending", "processing", "publishing", "published", "failed", "cancelled")
ACTIVE_PUBLICATION_STATUSES = ("pending", "processing", "publishing")


class ContentPublication(Base):
    """A publishing job: one draft published to one social account."""

    __tablename__ = "content_publications"
    __table_args__ = (
        Index("ix_content_publications_project_status", "project_id", "status"),
        Index("ix_content_publications_account", "social_account_id"),
        Index("ix_content_publications_workspace_created", "workspace_id", "created_at"),
        Index("ix_content_publications_due", "status", "next_attempt_at"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_content_publication_idempotency"),
        UniqueConstraint("active_guard", name="uq_content_publication_active_guard"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'publishing', 'published', 'failed', 'cancelled')",
            name="ck_content_publication_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Set while a job is active or published so the database rejects a second
    # concurrent/duplicate publication of the same draft to the same account.
    active_guard: Mapped[str | None] = mapped_column(String(120), nullable=True)
    content_version_number: Mapped[int | None] = mapped_column(nullable=True)
    caption: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str | None] = mapped_column(String(40))
    external_container_id: Mapped[str | None] = mapped_column(String(255))
    external_child_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    permalink: Mapped[str | None] = mapped_column(String(2048))
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(default=3, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(120))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_category: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(64))
    requires_user_action: Mapped[bool] = mapped_column(default=False, nullable=False)
    outcome_uncertain: Mapped[bool] = mapped_column(default=False, nullable=False)
    platform_response: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    draft_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_drafts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    social_account_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("social_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    media_asset_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    external_post_id: Mapped[str | None] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    attempts: Mapped[list[PublishingAttempt]] = relationship(
        back_populates="publication",
        cascade="all, delete-orphan",
        order_by="PublishingAttempt.attempt_number",
    )


class PublishingAttempt(Base):
    __tablename__ = "publishing_attempts"
    __table_args__ = (
        UniqueConstraint("publication_id", "attempt_number", name="uq_publishing_attempt_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    publication_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_publications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    stage: Mapped[str | None] = mapped_column(String(40))
    worker_id: Mapped[str | None] = mapped_column(String(120))
    error_category: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(default=False, nullable=False)
    response_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    publication: Mapped[ContentPublication] = relationship(back_populates="attempts")


class ContentVersion(Base):
    __tablename__ = "content_versions"
    __table_args__ = (
        Index("ix_content_versions_draft_number", "draft_id", "version_number"),
        UniqueConstraint("draft_id", "version_number", name="uq_content_version_draft_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    draft_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_drafts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(default=1, nullable=False)
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    hook: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    cta: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    change_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    draft: Mapped[ContentDraft] = relationship(back_populates="versions")


class ContentApproval(Base):
    __tablename__ = "content_approvals"
    __table_args__ = (
        Index("ix_content_approvals_project_status", "project_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    draft_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("content_drafts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    comments: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped[ContentProject] = relationship(back_populates="approvals")
    draft: Mapped[ContentDraft | None] = relationship(back_populates="approvals")
