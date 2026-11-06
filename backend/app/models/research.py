from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.user import utc_now

if TYPE_CHECKING:
    from app.models.brand import Brand
    from app.models.user import User
    from app.models.workspace import Workspace


class ResearchProject(Base):
    __tablename__ = "research_projects"
    __table_args__ = (
        Index("ix_research_projects_workspace", "workspace_id"),
        Index("ix_research_projects_brand", "brand_id"),
        Index("ix_research_projects_status", "status"),
        CheckConstraint(
            "status IN ('PENDING', 'PLANNING', 'SEARCHING', 'RETRIEVING', 'ANALYZING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_research_project_status",
        ),
        CheckConstraint(
            "current_stage IN ('PENDING', 'PLANNING', 'SEARCHING', 'RETRIEVING', 'ANALYZING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_research_project_stage",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    research_question: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    target_audience: Mapped[str | None] = mapped_column(String(160), nullable=True)
    geographic_scope: Mapped[str | None] = mapped_column(String(120), nullable=True)
    language: Mapped[str] = mapped_column(String(40), default="en", nullable=False)
    recency_preference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    research_depth: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    current_stage: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace: Mapped[Workspace] = relationship("Workspace")
    brand: Mapped[Brand | None] = relationship("Brand")
    creator: Mapped[User] = relationship("User")
    queries: Mapped[list[ResearchQuery]] = relationship(
        "ResearchQuery", back_populates="research_project", cascade="all, delete-orphan"
    )
    sources: Mapped[list[ResearchSource]] = relationship(
        "ResearchSource", back_populates="research_project", cascade="all, delete-orphan"
    )
    findings: Mapped[list[ResearchFinding]] = relationship(
        "ResearchFinding", back_populates="research_project", cascade="all, delete-orphan"
    )
    report: Mapped[ResearchReport | None] = relationship(
        "ResearchReport", back_populates="research_project", cascade="all, delete-orphan", uselist=False
    )
    usage_logs: Mapped[list[ResearchUsageLog]] = relationship(
        "ResearchUsageLog", back_populates="research_project", cascade="all, delete-orphan"
    )


class ResearchQuery(Base):
    __tablename__ = "research_queries"
    __table_args__ = (
        Index("ix_research_queries_research_id", "research_id"),
        Index("ix_research_queries_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    research_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    query_type: Mapped[str] = mapped_column(String(40), default="topic", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    research_project: Mapped[ResearchProject] = relationship("ResearchProject", back_populates="queries")


class ResearchSource(Base):
    __tablename__ = "research_sources"
    __table_args__ = (
        Index("ix_research_sources_research_id", "research_id"),
        Index("ix_research_sources_domain", "domain"),
        Index("ix_research_sources_retrieval_status", "retrieval_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    research_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), default="web", nullable=False)
    retrieval_status: Mapped[str] = mapped_column(String(40), default="PENDING", nullable=False)
    quality_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=dict, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    research_project: Mapped[ResearchProject] = relationship("ResearchProject", back_populates="sources")


class ResearchFinding(Base):
    __tablename__ = "research_findings"
    __table_args__ = (Index("ix_research_findings_research_id", "research_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    research_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    finding_type: Mapped[str] = mapped_column(String(80), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_label: Mapped[str] = mapped_column(String(40), default="MEDIUM", nullable=False)
    supporting_source_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    research_project: Mapped[ResearchProject] = relationship("ResearchProject", back_populates="findings")


class ResearchReport(Base):
    __tablename__ = "research_reports"
    __table_args__ = (Index("ix_research_reports_research_id", "research_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    research_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("research_projects.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    executive_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_findings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    trends: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    opportunities: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    risks: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    audience_insights: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    competitor_insights: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    content_angles: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    limitations: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    generated_by_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    research_project: Mapped[ResearchProject] = relationship("ResearchProject", back_populates="report")


class ResearchUsageLog(Base):
    __tablename__ = "research_usage_logs"
    __table_args__ = (
        Index("ix_research_usage_logs_workspace", "workspace_id"),
        Index("ix_research_usage_logs_research_id", "research_id"),
        CheckConstraint(
            "status IN ('PENDING', 'PLANNING', 'SEARCHING', 'RETRIEVING', 'ANALYZING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_research_usage_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    research_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    search_provider: Mapped[str] = mapped_column(String(80), nullable=False)
    ai_provider: Mapped[str] = mapped_column(String(80), default="groq", nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    search_requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    research_project: Mapped[ResearchProject] = relationship("ResearchProject", back_populates="usage_logs")


__all__ = [
    "ResearchFinding",
    "ResearchProject",
    "ResearchQuery",
    "ResearchReport",
    "ResearchSource",
    "ResearchUsageLog",
]
