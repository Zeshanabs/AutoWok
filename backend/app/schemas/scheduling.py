from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.schemas.publishing import PublicationRead
from app.services.scheduling.timezones import ensure_utc


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class UTCModel(APIModel):
    """Serializes every datetime as ISO 8601 in UTC with a trailing ``Z``."""

    @field_serializer("*", when_used="json", check_fields=False)
    def _serialize(self, value):  # type: ignore[no-untyped-def]
        if isinstance(value, datetime):
            return ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")
        return value


_LOCAL_PATTERN = r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?$"
_LOCAL_DESCRIPTION = "Wall-clock date and time in the selected timezone, e.g. 2026-11-20T09:30"


def local_field(**kwargs):  # type: ignore[no-untyped-def]
    return Field(pattern=_LOCAL_PATTERN, description=_LOCAL_DESCRIPTION, **kwargs)


class ScheduleCreate(APIModel):
    draft_id: UUID
    social_account_id: UUID
    scheduled_local: str = local_field()
    timezone: str = Field(min_length=1, max_length=64)
    project_id: UUID | None = None
    brand_id: UUID | None = None
    ambiguous: Literal["earlier", "later"] | None = None
    confirm: bool = Field(description="Must be true: the user confirmed the schedule.")


class ScheduleUpdate(APIModel):
    scheduled_local: str | None = local_field(default=None)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    social_account_id: UUID | None = None
    ambiguous: Literal["earlier", "later"] | None = None


class ScheduleReschedule(APIModel):
    scheduled_local: str = local_field()
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    ambiguous: Literal["earlier", "later"] | None = None


class ScheduleRetry(APIModel):
    confirm_not_published: bool = False


class SchedulingHistoryRead(UTCModel):
    id: UUID
    action: str
    previous_scheduled_at: datetime | None
    new_scheduled_at: datetime | None
    performed_by: UUID | None
    performed_by_name: str | None = None
    details: dict
    created_at: datetime


class ScheduledPostRead(UTCModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    draft_id: UUID
    social_account_id: UUID
    brand_id: UUID | None
    platform: str
    scheduled_at: datetime
    scheduled_local: str
    timezone: str
    utc_offset: str
    status: str
    stored_status: str
    revision: int
    content_version_number: int
    current_content_version: int | None
    content_changed: bool
    approval_status: str | None
    publication_id: UUID | None
    last_error: str | None
    created_by: UUID | None
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime
    queued_at: datetime | None
    cancelled_at: datetime | None
    published_at: datetime | None
    title: str | None = None
    caption_preview: str | None = None
    brand_name: str | None = None
    account_name: str | None = None
    account_platform: str | None = None
    account_status: str | None = None
    permalink: str | None = None
    can_edit: bool = False
    can_cancel: bool = False
    can_retry: bool = False
    publication: PublicationRead | None = None
    history: list[SchedulingHistoryRead] = Field(default_factory=list)


class CalendarItem(UTCModel):
    kind: Literal["scheduled", "published"]
    id: UUID
    scheduled_post_id: UUID | None
    publication_id: UUID | None
    project_id: UUID
    draft_id: UUID | None
    title: str | None
    caption_preview: str | None
    brand_id: UUID | None
    brand_name: str | None
    platform: str
    social_account_id: UUID | None
    account_name: str | None
    at: datetime
    local_time: str
    local_date: date
    timezone: str
    status: str
    approval_status: str | None
    content_changed: bool = False
    last_error: str | None = None
    permalink: str | None = None
    can_edit: bool = False
    can_cancel: bool = False


class UnscheduledItem(APIModel):
    project_id: UUID
    draft_id: UUID
    title: str | None
    caption_preview: str | None
    platform: str
    brand_id: UUID | None
    brand_name: str | None


class CalendarRead(UTCModel):
    view: str
    timezone: str
    anchor_date: date
    range_start: datetime
    range_end: datetime
    days: list[date]
    items: list[CalendarItem]
    unscheduled: list[UnscheduledItem]


class QueueStatusRead(UTCModel):
    counts: dict[str, int]
    schedule_counts: dict[str, int]
    next_scheduled_at: datetime | None
    active_jobs: list[PublicationRead]
    retrying_jobs: list[PublicationRead]
    attention_jobs: list[PublicationRead]
    upcoming: list[ScheduledPostRead]


class PreferencesRead(APIModel):
    timezone: str
    timezone_is_default: bool
    default_timezone: str


class PreferencesUpdate(APIModel):
    timezone: str | None = Field(default=None, max_length=64)


class TimezoneList(APIModel):
    timezones: list[str]
