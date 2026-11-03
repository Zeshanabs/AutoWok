from __future__ import annotations

from datetime import datetime
from typing import Any, TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.user import utc_now

if TYPE_CHECKING:
    from app.models.workspace import Workspace


class Brand(Base):
    __tablename__ = "brands"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_brand_workspace_slug"),
        Index("ix_brands_workspace_status", "workspace_id", "status"),
        CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="ck_brand_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(String(2048))
    industry: Mapped[str | None] = mapped_column(String(120))
    business_type: Mapped[str | None] = mapped_column(String(120))
    logo_url: Mapped[str | None] = mapped_column(String(2048))
    primary_color: Mapped[str | None] = mapped_column(String(7))
    secondary_color: Mapped[str | None] = mapped_column(String(7))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    workspace: Mapped[Workspace] = relationship("Workspace")
    voice: Mapped[BrandVoice | None] = relationship(
        back_populates="brand", cascade="all, delete-orphan", uselist=False
    )
    audiences: Mapped[list[TargetAudience]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    pillars: Mapped[list[ContentPillar]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    goals: Mapped[list[BrandGoal]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    policies: Mapped[list[BrandPolicy]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )


class BrandVoice(Base):
    __tablename__ = "brand_voices"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    brand_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    tone: Mapped[str | None] = mapped_column(String(120))
    personality: Mapped[str | None] = mapped_column(Text)
    writing_style: Mapped[str | None] = mapped_column(Text)
    communication_style: Mapped[str | None] = mapped_column(Text)
    vocabulary_preferences: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    preferred_phrases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    prohibited_phrases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    language_preferences: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    emoji_policy: Mapped[str | None] = mapped_column(String(24))
    hashtag_policy: Mapped[str | None] = mapped_column(String(24))
    call_to_action_style: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    brand: Mapped[Brand] = relationship(back_populates="voice")


class TargetAudience(Base):
    __tablename__ = "target_audiences"
    __table_args__ = (Index("ix_target_audiences_brand", "brand_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    brand_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    audience_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    age_range: Mapped[str | None] = mapped_column(String(40))
    locations: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    interests: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    pain_points: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    goals: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    preferred_platforms: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    demographics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    brand: Mapped[Brand] = relationship(back_populates="audiences")


class ContentPillar(Base):
    __tablename__ = "content_pillars"
    __table_args__ = (Index("ix_content_pillars_brand_active", "brand_id", "is_active"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    brand_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    objective: Mapped[str | None] = mapped_column(Text)
    suggested_topics: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    brand: Mapped[Brand] = relationship(back_populates="pillars")


class BrandGoal(Base):
    __tablename__ = "brand_goals"
    __table_args__ = (Index("ix_brand_goals_brand_active", "brand_id", "is_active"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    brand_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    goal_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    target_metric: Mapped[str | None] = mapped_column(String(120))
    target_value: Mapped[str | None] = mapped_column(String(120))
    target_period: Mapped[str | None] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    brand: Mapped[Brand] = relationship(back_populates="goals")


class BrandPolicy(Base):
    __tablename__ = "brand_policies"
    __table_args__ = (
        Index("ix_brand_policies_brand_active", "brand_id", "is_active"),
        CheckConstraint("severity IN ('LOW', 'MEDIUM', 'HIGH')", name="ck_brand_policy_severity"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    brand_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    policy_type: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    policy_value: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    brand: Mapped[Brand] = relationship(back_populates="policies")
