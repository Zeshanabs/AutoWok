from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.scheduling.timezones import ensure_utc


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    @field_serializer("*", when_used="json", check_fields=False)
    def _serialize(self, value):  # type: ignore[no-untyped-def]
        if isinstance(value, datetime):
            return ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")
        return value


Platform = Literal["facebook_page", "instagram"]


class FiltersRead(APIModel):
    start: date
    end: date
    days: int
    previous_start: date
    previous_end: date
    brand_id: UUID | None
    platform: str | None
    social_account_id: UUID | None
    account_ids: list[UUID]
    timezone_note: str


class PlatformMetricRead(APIModel):
    platform: str
    platform_label: str
    value: float | None
    previous_value: float | None
    change_percent: float | None
    availability: str
    reason: str | None = None
    definition: str | None
    source_metric: str | None
    unit: str = "count"
    aggregation: str | None = None
    collected_at: datetime | None
    accounts_with_data: int = 0
    accounts_total: int = 0
    days_with_data: int = 0


class MetricSummaryRead(APIModel):
    key: str
    label: str
    comparable: bool
    combined_value: float | None
    combined_note: str | None
    platforms: list[PlatformMetricRead]


class SyncStatusRead(APIModel):
    social_account_id: UUID
    account_name: str
    platform: str
    connection_status: str
    last_synced_at: datetime | None
    last_sync_status: str | None
    last_error: str | None
    last_error_category: str | None
    next_attempt_at: datetime | None
    active_job_id: UUID | None
    insights_available: bool
    can_sync: bool
    missing_permissions: list[str]
    notes: list[str]


class FollowerGrowthRead(APIModel):
    social_account_id: UUID
    account_name: str
    platform: str
    change: float | None
    snapshots: int
    latest: float | None
    note: str | None


class PublishedCountsRead(APIModel):
    total: int
    by_platform: dict[str, int]
    from_autowok: int
    previous_total: int
    change_percent: float | None


class PostRead(APIModel):
    id: UUID
    workspace_id: UUID
    brand_id: UUID | None
    social_account_id: UUID
    account_name: str | None
    platform: str
    platform_label: str
    publication_id: UUID | None
    project_id: UUID | None
    project_title: str | None
    draft_id: UUID | None
    external_post_id: str
    permalink: str | None
    published_at: datetime | None
    content_format: str | None
    content_format_label: str | None
    caption_preview: str | None
    thumbnail_url: str | None
    metrics: dict[str, int | None]
    extra_metrics: dict[str, Any]
    metric_availability: dict[str, str]
    engagement_rate: float | None
    engagement_rate_note: str | None
    engagement_definition: str | None
    reach_definition: str | None
    source: str
    collected_at: datetime | None
    api_version: str | None


class PostHistoryEntryRead(APIModel):
    snapshot_date: date
    collected_at: datetime | None
    metrics: dict[str, int | None]


class PostDetailRead(PostRead):
    history: list[PostHistoryEntryRead]
    definitions: list[dict[str, Any]]


class PostListRead(APIModel):
    total: int
    offset: int
    limit: int
    items: list[PostRead]


class OverviewRead(APIModel):
    filters: FiltersRead
    accounts: list[SyncStatusRead]
    metrics: list[MetricSummaryRead]
    follower_growth: list[FollowerGrowthRead]
    published_posts: PublishedCountsRead
    top_posts: list[PostRead]
    freshness: dict[str, datetime | None]
    notes: list[str]


class SeriesPointRead(APIModel):
    date: date
    value: float | None


class SeriesRead(APIModel):
    key: str
    label: str
    platform: str
    metric_label: str
    definition: str | None
    source_metric: str | None
    unit: str
    supported: bool
    has_data: bool
    points: list[SeriesPointRead]


class TimeseriesRead(APIModel):
    metric: str
    group_by: str
    start: date
    end: date
    series: list[SeriesRead]


class AccountMetricRead(APIModel):
    key: str
    label: str
    value: float | None
    previous_value: float | None
    change_percent: float | None
    availability: str
    reason: str | None = None
    definition: str | None
    source_metric: str | None
    unit: str = "count"
    aggregation: str | None = None
    collected_at: datetime | None
    accounts_with_data: int = 0
    accounts_total: int = 0
    days_with_data: int = 0


class AccountSummaryRead(APIModel):
    id: UUID
    display_name: str
    username: str | None
    platform: str
    platform_label: str
    brand_id: UUID | None
    profile_image_url: str | None
    connection_status: str


class AccountInsightsRead(APIModel):
    account: AccountSummaryRead
    metrics: list[AccountMetricRead]
    follower_series: list[SeriesPointRead]
    follower_change: float | None
    sync: SyncStatusRead


class CompareRequest(APIModel):
    post_ids: list[UUID] = Field(min_length=2, max_length=6)


class CompareRead(APIModel):
    posts: list[PostRead]
    metrics: list[dict[str, Any]]
    mixed_platforms: bool


class PlatformComparisonRead(APIModel):
    filters: FiltersRead
    platforms: list[dict[str, Any]]
    account_metrics: list[MetricSummaryRead]
    post_metrics: list[dict[str, Any]]
    engagement_rates: list[dict[str, Any]]
    meaningful: bool
    note: str


class ContentPerformanceRead(APIModel):
    filters: FiltersRead
    post_count: int
    ranking_metric: str
    ranking_method: str
    top_posts: list[PostRead]
    bottom_posts: list[PostRead]
    formats: list[dict[str, Any]]
    best_format: dict[str, Any] | None
    best_format_note: str
    weekly_trend: list[dict[str, Any]]
    period_change: dict[str, Any]
    consistency: dict[str, Any]
    notes: list[str]


class SummaryRead(APIModel):
    available: bool
    label: str
    reason: str | None
    text: str | None
    model: str | None


class SyncRequest(APIModel):
    social_account_id: UUID | None = None


class SyncJobRead(APIModel):
    id: UUID
    workspace_id: UUID
    social_account_id: UUID
    account_name: str | None = None
    platform: str
    status: str
    trigger: str
    requested_by: UUID | None
    range_start: date | None
    range_end: date | None
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    error_category: str | None
    error_code: str | None
    last_error: str | None
    records_processed: int
    details: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SyncRequestRead(APIModel):
    jobs: list[SyncJobRead]
    skipped: list[dict[str, Any]]


class SyncStatusListRead(APIModel):
    accounts: list[SyncStatusRead]
    active_jobs: int
    sync_interval_hours: float


class ReportRead(APIModel):
    title: str
    generated_at: datetime
    period: dict[str, Any]
    previous_period: dict[str, Any]
    brand: dict[str, Any]
    platform_filter: str | None
    accounts: list[dict[str, Any]]
    key_metrics: list[MetricSummaryRead]
    follower_growth: list[FollowerGrowthRead]
    published_posts: PublishedCountsRead
    account_insights: list[AccountInsightsRead]
    posts: list[PostRead]
    definitions: list[dict[str, Any]]
    missing_data: list[str]
    collection: dict[str, Any]
