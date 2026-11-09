from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class APIModel(BaseModel):
    model_config = {"from_attributes": True, "extra": "forbid"}


class IdeaRequest(APIModel):
    workspace_id: str | None = None
    topic: str | None = None
    objective: str | None = None
    platform: str = "instagram"
    language: str = "en"
    content_type: str = "social content"
    brand_id: str | None = None
    research_report_id: str | None = None
    brand: dict[str, Any] | None = None
    research: dict[str, Any] | None = None


class WritingRequest(APIModel):
    workspace_id: str | None = None
    text: str = ""
    action: str = "improve writing"
    platform: str = "instagram"
    tone: str = "Professional"
    objective: str = "drive engagement"
    brand: dict[str, Any] | None = None


class CritiqueRequest(APIModel):
    workspace_id: str | None = None
    text: str = ""
    brand: dict[str, Any] | None = None


class FactCheckRequest(APIModel):
    workspace_id: str | None = None
    claims: list[str] = Field(default_factory=list)
    research: dict[str, Any] | None = None


class IdeaResponse(APIModel):
    ideas: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    workspace_id: str | None = None


class WritingResponse(APIModel):
    output: str = ""
    hook: str | None = None
    cta: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    readability_score: int | None = None
    brand_alignment: str | None = None
