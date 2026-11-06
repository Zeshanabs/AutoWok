from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class APIModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        use_enum_values=True,
        extra="forbid",
        protected_namespaces=(),
    )


class ContentPlatform(StrEnum):
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"


class ContentType(StrEnum):
    TEXT_POST = "text_post"
    IMAGE_POST = "image_post"
    CAROUSEL = "carousel"
    REEL = "reel"
    STORY = "story"
    PROMOTIONAL = "promotional"
    EDUCATIONAL = "educational"
    ANNOUNCEMENT = "announcement"
    TESTIMONIAL = "testimonial"
    PRODUCT_PROMOTION = "product_promotion"
    ENGAGEMENT = "engagement"


class ContentProjectStatus(StrEnum):
    DRAFT = "draft"
    READY_FOR_REVIEW = "ready_for_review"
    IN_REVIEW = "in_review"
    REJECTED = "rejected"
    APPROVED = "approved"
    ARCHIVED = "archived"


class DraftStatus(StrEnum):
    DRAFT = "draft"
    READY_FOR_REVIEW = "ready_for_review"
    IN_REVIEW = "in_review"
    REJECTED = "rejected"
    APPROVED = "approved"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class ApprovalDecisionStatus(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class ContentProjectCreate(APIModel):
    workspace_id: UUID
    title: str = Field(min_length=2, max_length=200)
    topic: str | None = Field(default=None, max_length=3000)
    objective: str | None = Field(default=None, max_length=3000)
    brand_id: UUID | None = None
    selected_platforms: list[ContentPlatform] = Field(default_factory=lambda: [ContentPlatform.INSTAGRAM])
    content_type: ContentType = ContentType.TEXT_POST
    content_pillar: str | None = Field(default=None, max_length=160)
    target_audience: str | None = Field(default=None, max_length=200)
    preferred_tone: str | None = Field(default=None, max_length=80)
    language: str = Field(default="en", min_length=2, max_length=20)
    keywords: list[str] = Field(default_factory=list)
    required_phrases: list[str] = Field(default_factory=list)
    prohibited_phrases: list[str] = Field(default_factory=list)
    cta_requirements: str | None = Field(default=None, max_length=400)
    hashtag_preferences: str | None = Field(default=None, max_length=400)
    emoji_preferences: str | None = Field(default=None, max_length=200)
    desired_length: str | None = Field(default=None, max_length=40)
    research_report_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("A project title is required.")
        return title

    @field_validator("selected_platforms")
    @classmethod
    def validate_platforms(cls, value: list[ContentPlatform]) -> list[ContentPlatform]:
        normalized = list(dict.fromkeys(str(item) for item in value))
        if not normalized:
            raise ValueError("Select at least one platform.")
        return [ContentPlatform(platform) for platform in normalized]

    @field_validator("keywords", "required_phrases", "prohibited_phrases")
    @classmethod
    def clean_lists(cls, value: list[str]) -> list[str]:
        cleaned = []
        for item in value:
            text = " ".join(str(item).split())
            if text:
                cleaned.append(text)
        return cleaned


class ContentProjectUpdate(APIModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    topic: str | None = Field(default=None, max_length=3000)
    objective: str | None = Field(default=None, max_length=3000)
    brand_id: UUID | None = None
    selected_platforms: list[ContentPlatform] | None = None
    content_type: ContentType | None = None
    content_pillar: str | None = Field(default=None, max_length=160)
    target_audience: str | None = Field(default=None, max_length=200)
    preferred_tone: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, min_length=2, max_length=20)
    keywords: list[str] | None = None
    required_phrases: list[str] | None = None
    prohibited_phrases: list[str] | None = None
    cta_requirements: str | None = Field(default=None, max_length=400)
    hashtag_preferences: str | None = Field(default=None, max_length=400)
    emoji_preferences: str | None = Field(default=None, max_length=200)
    desired_length: str | None = Field(default=None, max_length=40)
    research_report_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        title = value.strip()
        if not title:
            raise ValueError("A project title is required.")
        return title

    @field_validator("selected_platforms")
    @classmethod
    def validate_platforms(
        cls, value: list[ContentPlatform] | None
    ) -> list[ContentPlatform] | None:
        if value is None:
            return None
        normalized = list(dict.fromkeys(str(item) for item in value))
        if not normalized:
            raise ValueError("Select at least one platform.")
        return [ContentPlatform(platform) for platform in normalized]

    @field_validator("keywords", "required_phrases", "prohibited_phrases")
    @classmethod
    def clean_optional_lists(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [" ".join(item.split()) for item in value if item.strip()]


class ContentProjectRead(APIModel):
    id: UUID
    workspace_id: UUID
    brand_id: UUID | None
    created_by: UUID
    title: str
    topic: str | None
    objective: str | None
    content_type: str
    selected_platforms: list[str]
    content_pillar: str | None
    target_audience: str | None
    preferred_tone: str | None
    language: str
    keywords: list[str]
    required_phrases: list[str]
    prohibited_phrases: list[str]
    cta_requirements: str | None
    hashtag_preferences: str | None
    emoji_preferences: str | None
    desired_length: str | None
    research_report_id: UUID | None
    status: str
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    approved_at: datetime | None


class ContentDraftCreate(APIModel):
    platform: ContentPlatform
    title: str | None = Field(default=None, max_length=200)
    hook: str | None = Field(default=None, max_length=2200)
    body: str | None = Field(default=None, max_length=2200)
    cta: str | None = Field(default=None, max_length=200)
    hashtags: list[str] = Field(default_factory=list)
    ai_generated: bool = False

    @field_validator("hashtags")
    @classmethod
    def clean_hashtags(cls, value: list[str]) -> list[str]:
        return [" ".join(tag.split()) for tag in value if tag.strip()]


class ContentDraftUpdate(APIModel):
    title: str | None = Field(default=None, max_length=200)
    hook: str | None = Field(default=None, max_length=2200)
    body: str | None = Field(default=None, max_length=2200)
    cta: str | None = Field(default=None, max_length=200)
    hashtags: list[str] | None = None

    @field_validator("hashtags")
    @classmethod
    def clean_hashtags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [" ".join(tag.split()) for tag in value if tag.strip()]


class DraftVersionRead(APIModel):
    id: UUID
    draft_id: UUID
    version_number: int
    platform: str
    title: str | None
    hook: str | None
    body: str | None
    cta: str | None
    hashtags: list[str]
    snapshot: dict | None
    change_reason: str | None
    created_by: UUID | None
    created_at: datetime


class ContentDraftRead(APIModel):
    id: UUID
    project_id: UUID
    platform: str
    title: str | None
    hook: str | None
    body: str | None
    cta: str | None
    hashtags: list[str]
    status: str
    ai_generated: bool
    version_count: int
    created_at: datetime
    updated_at: datetime
    versions: list[DraftVersionRead] = Field(default_factory=list)


class ContentApprovalSubmit(APIModel):
    comments: str | None = Field(default=None, max_length=5000)


class ContentApprovalDecision(APIModel):
    status: ApprovalDecisionStatus
    comments: str | None = Field(default=None, max_length=5000)


class PlatformValidationRead(APIModel):
    platform: ContentPlatform
    valid: bool
    caption_length: int
    hashtag_count: int
    errors: list[str]
    warnings: list[str]


class ContentApprovalRead(APIModel):
    id: UUID
    project_id: UUID
    draft_id: UUID | None
    status: str
    comments: str | None
    reviewed_by: UUID | None
    created_at: datetime
    updated_at: datetime


class GeneratedDraftPayload(APIModel):
    title: str
    hook: str
    body: str
    cta: str
    hashtags: list[str]
    platform: str
    variations: list[str] = Field(default_factory=list)


class GenerateContentRequest(APIModel):
    platform: ContentPlatform | None = None
    force_regenerate: bool = False
