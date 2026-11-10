from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class MediaAssetRead(APIModel):
    id: UUID
    workspace_id: UUID
    brand_id: UUID | None = None
    original_filename: str
    title: str | None = None
    media_type: str
    mime_type: str
    file_extension: str
    file_size: int
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    checksum: str
    has_thumbnail: bool = False
    metadata_stripped: bool = False
    storage_provider: str
    processing_status: str
    uploaded_by: UUID
    archived: bool = False
    created_at: datetime
    updated_at: datetime
    content_url: str
    download_url: str
    thumbnail_url: str | None = None
    duplicate: bool = False


class MediaAssetUpdate(APIModel):
    title: str | None = Field(default=None, max_length=200)
    brand_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None


class MediaAccessUrl(APIModel):
    url: str
    expires_in_seconds: int


class DraftMediaAttachment(APIModel):
    media_asset_ids: list[str] = Field(default_factory=list, max_length=20)


class PreviewMediaItem(APIModel):
    id: UUID
    media_type: str
    mime_type: str
    title: str
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    content_url: str
    thumbnail_url: str | None = None


class DraftPreview(APIModel):
    platform: str
    preview_type: str | None
    approximate: bool = True
    disclaimer: str = (
        "This preview is an approximation. The live post may look different on Facebook or Instagram."
    )
    supports_multiple_attachments: bool = False
    media_count: int = 0
    caption: str | None = None
    caption_length: int = 0
    account_name: str | None = None
    account_username: str | None = None
    account_image_url: str | None = None
    media: list[PreviewMediaItem] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    attachment_names: list[str] = Field(default_factory=list)
