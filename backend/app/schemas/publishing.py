from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class PublishValidateRequest(APIModel):
    social_account_id: UUID


class PublishRequest(APIModel):
    social_account_id: UUID
    confirm: bool = Field(description="Must be true: the user explicitly confirmed immediate publishing.")
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


class RetryRequest(APIModel):
    confirm_not_published: bool = False


class EligibilityRead(APIModel):
    eligible: bool
    platform: str
    publish_format: str | None
    approval_status: str | None
    content_version_number: int | None
    caption: str
    media_count: int
    errors: list[str]
    warnings: list[str]
    social_account_id: UUID
    account_name: str | None = None
    account_platform: str | None = None


class PublishingAttemptRead(APIModel):
    id: UUID
    attempt_number: int
    status: str
    stage: str | None
    error_category: str | None
    error_code: str | None
    error_message: str | None
    retryable: bool
    started_at: datetime
    finished_at: datetime | None


class PublicationRead(APIModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    draft_id: UUID | None
    social_account_id: UUID | None
    platform: str
    source: str
    status: str
    stage: str | None
    publish_format: str | None = None
    caption: str | None
    media_asset_ids: list[str]
    content_version_number: int | None
    external_post_id: str | None
    permalink: str | None
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None
    error_category: str | None
    error_code: str | None
    error_message: str | None
    requires_user_action: bool
    outcome_uncertain: bool
    can_retry: bool = False
    can_cancel: bool = False
    requested_by: UUID | None
    confirmed_at: datetime | None
    started_at: datetime | None
    published_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    project_title: str | None = None
    account_name: str | None = None
    attempts: list[PublishingAttemptRead] = Field(default_factory=list)
