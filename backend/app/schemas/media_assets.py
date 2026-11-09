from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class MediaAssetRead(APIModel):
    id: UUID
    workspace_id: UUID
    brand_id: UUID | None = None
    original_filename: str
    storage_key: str
    mime_type: str
    file_extension: str
    file_size: int
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    checksum: str
    thumbnail_key: str | None = None
    storage_provider: str
    processing_status: str
    uploaded_by: UUID
    archived: bool = False
    created_at: datetime
    updated_at: datetime
    download_url: str | None = None
    thumbnail_url: str | None = None


class DraftMediaAttachment(APIModel):
    media_asset_ids: list[str] = Field(default_factory=list)


class DraftPreview(APIModel):
    platform: str
    preview_type: str
    approximate: bool = True
    supports_multiple_attachments: bool = False
    media_count: int = 0
    caption: str | None = None
    warnings: list[str] = Field(default_factory=list)
    attachment_names: list[str] = Field(default_factory=list)
