"""Normalized analytics storage with duplicate prevention.

Snapshots are keyed by (account, metric, period, day) and posts by
(account, external post id). Re-collecting the same period *updates* the
existing row (Meta data can lag up to 48 hours), so repeated or retried
synchronizations never create duplicates.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from app.models import ContentPublication, PostAnalytics, PostAnalyticsHistory, SocialAccount
from app.models.analytics import AnalyticsSnapshot
from app.services.analytics import metrics as M
from app.services.analytics.collector import AccountCollection, CollectedPost


def _int_or_none(value: float | None) -> int | None:
    if value is None:
        return None
    return int(round(value))


def upsert_account_snapshots(
    db: DBSession,
    *,
    account: SocialAccount,
    collection: AccountCollection,
    collected_at: datetime,
    api_version: str,
) -> tuple[int, int]:
    """Insert or update daily snapshots. Returns ``(created, updated)``."""
    created = updated = 0
    if not collection.snapshots:
        return 0, 0
    days = {value.snapshot_date for value in collection.snapshots}
    keys = {value.key for value in collection.snapshots}
    existing = (
        db.query(AnalyticsSnapshot)
        .filter(
            AnalyticsSnapshot.social_account_id == account.id,
            AnalyticsSnapshot.period == "day",
            AnalyticsSnapshot.snapshot_date.in_(sorted(days)),
            AnalyticsSnapshot.metric_key.in_(sorted(keys)),
        )
        .all()
    )
    index = {(row.metric_key, row.snapshot_date): row for row in existing}
    seen: set[tuple[str, date]] = set()
    for value in collection.snapshots:
        identity = (value.key, value.snapshot_date)
        if identity in seen:
            continue  # the same (metric, day) appearing twice in one collection
        seen.add(identity)
        row = index.get(identity)
        if row is None:
            row = AnalyticsSnapshot(
                workspace_id=account.workspace_id,
                brand_id=account.brand_id,
                social_account_id=account.id,
                platform=account.platform,
                metric_key=value.key,
                source_metric=value.source,
                period="day",
                snapshot_date=value.snapshot_date,
            )
            db.add(row)
            index[identity] = row
            created += 1
        else:
            updated += 1
        row.brand_id = account.brand_id
        row.metric_value = value.value
        row.metric_unit = value.unit
        row.value_breakdown = value.breakdown
        row.source_metric = value.source
        row.api_version = api_version
        row.collected_at = collected_at
    db.flush()
    return created, updated


def find_publication_links(db: DBSession, account: SocialAccount) -> dict[str, ContentPublication]:
    """Map external post ids of posts Autowok published to this account."""
    rows = (
        db.query(ContentPublication)
        .filter(
            ContentPublication.social_account_id == account.id,
            ContentPublication.status == "published",
            ContentPublication.external_post_id.is_not(None),
        )
        .all()
    )
    return {row.external_post_id: row for row in rows if row.external_post_id}


def upsert_post(
    db: DBSession,
    *,
    account: SocialAccount,
    post: CollectedPost,
    publication: ContentPublication | None,
    collected_at: datetime,
    api_version: str,
) -> tuple[PostAnalytics, bool]:
    """Insert or update the post row and its history entry for the collection day."""
    row = (
        db.query(PostAnalytics)
        .filter(PostAnalytics.social_account_id == account.id, PostAnalytics.external_post_id == post.external_post_id)
        .first()
    )
    created = row is None
    if row is None:
        row = PostAnalytics(
            workspace_id=account.workspace_id,
            social_account_id=account.id,
            platform=account.platform,
            external_post_id=post.external_post_id,
        )
        db.add(row)
    brand_id = account.brand_id
    if publication is not None:
        row.publication_id = publication.id
        row.project_id = publication.project_id
        row.draft_id = publication.draft_id
        project = publication_project(db, publication)
        if project is not None and project.brand_id is not None:
            brand_id = project.brand_id
        if publication.published_at is not None and post.published_at is None:
            post.published_at = publication.published_at
        if post.permalink is None and publication.permalink:
            post.permalink = publication.permalink
    row.brand_id = brand_id
    row.permalink = post.permalink
    row.published_at = post.published_at
    row.content_format = post.content_format
    row.caption_preview = post.caption_preview
    row.thumbnail_url = post.thumbnail_url
    for key in M.POST_COLUMNS:
        setattr(row, key, _int_or_none(post.values.get(key)))
    extras = {key: value for key, value in post.values.items() if key not in M.POST_COLUMNS}
    row.raw_metrics = {**post.raw, **({"normalized_extras": extras} if extras else {})}
    row.metric_availability = dict(post.availability)
    row.api_version = api_version
    row.collected_at = collected_at
    db.flush()

    snapshot_day = collected_at.date()
    history = (
        db.query(PostAnalyticsHistory)
        .filter(PostAnalyticsHistory.post_analytics_id == row.id, PostAnalyticsHistory.snapshot_date == snapshot_day)
        .first()
    )
    if history is None:
        history = PostAnalyticsHistory(post_analytics_id=row.id, snapshot_date=snapshot_day)
        db.add(history)
    history.metrics = {key: _int_or_none(post.values.get(key)) for key in M.POST_COLUMNS}
    history.collected_at = collected_at
    db.flush()
    return row, created


def publication_project(db: DBSession, publication: ContentPublication):
    from app.models import ContentProject

    return db.get(ContentProject, publication.project_id) if publication.project_id else None


def snapshot_exists(db: DBSession, account_id: UUID) -> bool:
    return db.query(AnalyticsSnapshot.id).filter(AnalyticsSnapshot.social_account_id == account_id).first() is not None


def history_as_dict(entry: PostAnalyticsHistory) -> dict[str, Any]:
    return {"snapshot_date": entry.snapshot_date, "collected_at": entry.collected_at, "metrics": dict(entry.metrics or {})}
