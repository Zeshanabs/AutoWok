from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True, extra="forbid")


class ResearchStatus(StrEnum):
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    SEARCHING = "SEARCHING"
    RETRIEVING = "RETRIEVING"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ResearchDepth(StrEnum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"
    COMPREHENSIVE = "comprehensive"


class ResearchProjectCreate(APIModel):
    workspace_id: UUID
    brand_id: UUID | None = None
    title: str = Field(min_length=2, max_length=220)
    research_question: str = Field(min_length=2, max_length=10000)
    category: str = Field(default="General topic research", min_length=2, max_length=120)
    target_audience: str | None = Field(default=None, max_length=160)
    geographic_scope: str | None = Field(default=None, max_length=120)
    language: str = Field(default="en", min_length=2, max_length=40)
    recency_preference: str | None = Field(default=None, max_length=80)
    research_depth: str = Field(default=ResearchDepth.STANDARD.value, min_length=2, max_length=40)
    optional_keywords: list[str] = Field(default_factory=list)


class ResearchProjectUpdate(APIModel):
    title: str | None = Field(default=None, min_length=2, max_length=220)
    research_question: str | None = Field(default=None, min_length=2, max_length=10000)
    category: str | None = Field(default=None, min_length=2, max_length=120)
    target_audience: str | None = Field(default=None, max_length=160)
    geographic_scope: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, min_length=2, max_length=40)
    recency_preference: str | None = Field(default=None, max_length=80)
    research_depth: str | None = Field(default=None, min_length=2, max_length=40)
    status: ResearchStatus | None = None
    current_stage: ResearchStatus | None = None

class ResearchQueryRead(APIModel):
    id: UUID
    research_id: UUID
    query: str
    query_type: str
    status: str
    created_at: datetime


class ResearchSourceRead(APIModel):
    id: UUID
    research_id: UUID
    title: str
    url: str
    domain: str
    snippet: str | None = None
    extracted_content: str | None = None
    publication_date: datetime | None = None
    retrieved_at: datetime
    source_type: str
    retrieval_status: str
    quality_metadata: dict[str, Any] | None = None
    created_at: datetime


class ResearchFindingRead(APIModel):
    id: UUID
    research_id: UUID
    finding_type: str
    claim: str
    explanation: str | None = None
    confidence_label: str
    supporting_source_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class ResearchReportRead(APIModel):
    id: UUID
    research_id: UUID
    executive_summary: str | None = None
    key_findings: list[str] = Field(default_factory=list)
    trends: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    audience_insights: list[str] = Field(default_factory=list)
    competitor_insights: list[str] = Field(default_factory=list)
    content_angles: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    generated_by_model: str | None = None
    created_at: datetime
    updated_at: datetime


class ResearchProjectRead(APIModel):
    id: UUID
    workspace_id: UUID
    brand_id: UUID | None = None
    created_by: UUID
    title: str
    research_question: str
    category: str
    target_audience: str | None = None
    geographic_scope: str | None = None
    language: str
    recency_preference: str | None = None
    research_depth: str
    status: str
    current_stage: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class ResearchStatusRead(APIModel):
    research_id: UUID
    status: str
    current_stage: str
    updated_at: datetime


class ResearchExportRead(APIModel):
    format: str
    content: str


class SearchProviderConfig(APIModel):
    name: str
    api_key: str | None = None
    base_url: str | None = None
    max_results: int = 10
    timeout_seconds: int = 30
