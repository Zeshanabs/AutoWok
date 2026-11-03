from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas.brands import APIModel


class SocialPlatform(StrEnum):
    FACEBOOK_PAGE = "facebook_page"
    INSTAGRAM = "instagram"


class SocialAccountRead(APIModel):
    id: UUID
    workspace_id: UUID
    brand_id: UUID | None
    platform: SocialPlatform
    platform_account_id: str
    username: str | None
    display_name: str
    profile_image_url: str | None
    account_type: str | None
    parent_account_id: UUID | None
    connection_status: str
    granted_scopes: list[str]
    connected_by: UUID
    connected_at: datetime
    last_verified_at: datetime | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


class MetaPageOption(APIModel):
    platform_account_id: str
    display_name: str
    username: str | None = None
    category: str | None = None
    profile_image_url: str | None = None
    tasks: list[str] = Field(default_factory=list)


class InstagramAccountOption(APIModel):
    platform_account_id: str
    username: str | None = None
    account_type: str
    profile_image_url: str | None = None
    parent_page_id: str
    parent_page_name: str


class SocialAccountConnect(APIModel):
    platform: SocialPlatform
    platform_account_id: str = Field(min_length=1, max_length=255)
    brand_id: UUID | None = None
    parent_page_id: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def require_parent_page_for_instagram(self):
        if self.platform == SocialPlatform.INSTAGRAM and not self.parent_page_id:
            raise ValueError("Select the Facebook Page linked to this Instagram account.")
        if self.platform == SocialPlatform.FACEBOOK_PAGE and self.parent_page_id:
            raise ValueError("Facebook Page accounts cannot have a parent page.")
        return self

    @field_validator("platform_account_id", "parent_page_id")
    @classmethod
    def strip_ids(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class SocialAccountUpdate(APIModel):
    brand_id: UUID | None = None
