"""Read-side aggregations for the analytics API.

All functions take an ``AnalyticsFilters`` instance whose accounts were
resolved inside the caller's workspace, so no query here can cross a
workspace boundary. Values are only ever summed within one platform; a
cross-platform total is produced solely for keys that the metric catalogue
marks as comparable, and even then the per-platform definitions are returned
alongside it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.models import Brand, ContentProject, SocialAccount
from app.models.analytics import AnalyticsSnapshot, AnalyticsSyncJob, PostAnalytics
from app.services.analytics import calculations as C
from app.services.analytics import metrics as M
from app.services.analytics.sync import analytics_eligibility, last_job

OVERVIEW_KEYS = ("followers", "reach", "views", "engagements")
POST_SUMMARY_KEYS = ("reach", "views", "engagements", "likes", "comments", "shares", "saves", "clicks", "video_views")
POST_FORMAT_LABELS = {
    "text": "Text post",
    "photo": "Photo",
    "multi_photo": "Multi-photo",
    "video": "Video",
    "link": "Link",
    "other": "Other",
    "image": "Image",
    "carousel": "Carousel",
    "reel": "Reel",
    "story": "Story",
}
MIN_FORMAT_SAMPLE = 3
MIN_RANKING_SAMPLE = 2


@dataclass
class AnalyticsFilters:
    workspace_id: UUID
    start: date
    end: date
    brand_id: UUID | None = None
    platform: str | None = None
    social_account_id: UUID | None = None
    accounts: list[SocialAccount] = field(default_factory=list)

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def previous(self) -> tuple[date, date]:
        previous_end = self.start - timedelta(days=1)
        return previous_end - timedelta(days=self.days - 1), previous_end

    @property
    def account_ids(self) -> list[UUID]:
        return [account.id for account in self.accounts]

    def to_dict(self) -> dict[str, Any]:
        previous_start, previous_end = self.previous
        return {
            "start": self.start,
            "end": self.end,
            "days": self.days,
            "previous_start": previous_start,
            "previous_end": previous_end,
            "brand_id": self.brand_id,
            "platform": self.platform,
            "social_account_id": self.social_account_id,
            "account_ids": self.account_ids,
            "timezone_note": "Daily values follow Meta's reporting day for each account; post dates are compared in UTC.",
        }


def resolve_accounts(db: DBSession, filters: AnalyticsFilters) -> AnalyticsFilters:
    query = db.query(SocialAccount).filter(
        SocialAccount.workspace_id == filters.workspace_id,
        SocialAccount.platform.in_(M.PLATFORMS),
    )
    if filters.platform:
        query = query.filter(SocialAccount.platform == filters.platform)
    if filters.social_account_id:
        query = query.filter(SocialAccount.id == filters.social_account_id)
    if filters.brand_id:
        query = query.filter(SocialAccount.brand_id == filters.brand_id)
    filters.accounts = query.order_by(SocialAccount.created_at).all()
    return filters


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


# Snapshots ----------------------------------------------------------------------


def _snapshots(db: DBSession, account_ids: list[UUID], keys: tuple[str, ...] | None, start: date, end: date) -> list[AnalyticsSnapshot]:
    if not account_ids:
        return []
    query = db.query(AnalyticsSnapshot).filter(
        AnalyticsSnapshot.social_account_id.in_(account_ids),
        AnalyticsSnapshot.period == "day",
        AnalyticsSnapshot.snapshot_date >= start,
        AnalyticsSnapshot.snapshot_date <= end,
    )
    if keys:
        query = query.filter(AnalyticsSnapshot.metric_key.in_(list(keys)))
    return query.order_by(AnalyticsSnapshot.snapshot_date).all()


def _aggregate(rows: list[AnalyticsSnapshot], aggregation: str) -> dict[str, Any]:
    """Aggregate one metric for one platform over a period.

    ``sum`` adds every daily value; ``last`` takes the latest value per account
    and adds those (for example followers across two Pages).
    """
    values = [row for row in rows if row.metric_value is not None]
    if not values:
        return {"value": None, "collected_at": None, "days_with_data": 0, "accounts_with_data": 0}
    collected = max(_utc(row.collected_at) for row in values)
    accounts = {row.social_account_id for row in values}
    if aggregation == "last":
        latest: dict[UUID, AnalyticsSnapshot] = {}
        for row in values:
            current = latest.get(row.social_account_id)
            if current is None or row.snapshot_date > current.snapshot_date:
                latest[row.social_account_id] = row
        total = sum(row.metric_value for row in latest.values())
        return {"value": total, "collected_at": collected, "days_with_data": len({r.snapshot_date for r in values}), "accounts_with_data": len(accounts)}
    total = sum(row.metric_value for row in values)
    return {"value": total, "collected_at": collected, "days_with_data": len({r.snapshot_date for r in values}), "accounts_with_data": len(accounts)}


def _unavailable_reasons(db: DBSession, accounts: list[SocialAccount]) -> dict[UUID, dict[str, str]]:
    """Latest per-account reasons why metrics were unavailable, from the last sync job."""
    reasons: dict[UUID, dict[str, str]] = {}
    for account in accounts:
        job = last_job(db, account.id, statuses=("succeeded", "partial", "failed"))
        details = job.details if job is not None and isinstance(job.details, dict) else {}
        unavailable = details.get("unavailable") if isinstance(details.get("unavailable"), dict) else {}
        reasons[account.id] = {str(key): str(value) for key, value in unavailable.items()}
    return reasons


def account_metric_summary(db: DBSession, filters: AnalyticsFilters, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Per metric key: per-platform current/previous values with definitions."""
    previous_start, previous_end = filters.previous
    current_rows = _snapshots(db, filters.account_ids, keys, filters.start, filters.end)
    previous_rows = _snapshots(db, filters.account_ids, keys, previous_start, previous_end)
    reasons = _unavailable_reasons(db, filters.accounts)
    platforms = sorted({account.platform for account in filters.accounts}, key=M.PLATFORMS.index)
    result = []
    for key in keys:
        entries = []
        for platform in platforms:
            definition = M.definition(platform, M.ACCOUNT, key)
            platform_accounts = [account for account in filters.accounts if account.platform == platform]
            if definition is None:
                entries.append(
                    {
                        "platform": platform,
                        "platform_label": M.PLATFORM_LABELS[platform],
                        "value": None,
                        "previous_value": None,
                        "change_percent": None,
                        "availability": "not_supported",
                        "reason": M.NOT_SUPPORTED.get(platform, {}).get(key, "Not reported by this platform."),
                        "definition": None,
                        "source_metric": None,
                        "unit": "count",
                        "collected_at": None,
                        "accounts_with_data": 0,
                        "accounts_total": len(platform_accounts),
                    }
                )
                continue
            rows = [row for row in current_rows if row.platform == platform and row.metric_key == key]
            prev = [row for row in previous_rows if row.platform == platform and row.metric_key == key]
            current = _aggregate(rows, definition.aggregation)
            previous = _aggregate(prev, definition.aggregation)
            availability = "available" if current["value"] is not None else "unavailable"
            if current["value"] is not None and current["accounts_with_data"] < len(platform_accounts):
                availability = "partial"
            reason = None
            if availability != "available":
                for account in platform_accounts:
                    note = reasons.get(account.id, {}).get(key)
                    if note:
                        reason = _reason_text(note)
                        break
                if reason is None and availability == "unavailable":
                    reason = "No data has been collected for this period yet."
            entries.append(
                {
                    "platform": platform,
                    "platform_label": M.PLATFORM_LABELS[platform],
                    "value": current["value"],
                    "previous_value": previous["value"],
                    "change_percent": C.percentage_change(current["value"], previous["value"]),
                    "availability": availability,
                    "reason": reason,
                    "definition": definition.definition,
                    "source_metric": definition.source_name,
                    "unit": definition.unit,
                    "aggregation": definition.aggregation,
                    "collected_at": current["collected_at"],
                    "accounts_with_data": current["accounts_with_data"],
                    "accounts_total": len(platform_accounts),
                    "days_with_data": current["days_with_data"],
                }
            )
        comparable = M.is_comparable(M.ACCOUNT, key)
        combined = None
        if comparable and entries and all(entry["value"] is not None for entry in entries) and len(entries) > 1:
            combined = sum(entry["value"] for entry in entries)
        label = next((M.definition(e["platform"], M.ACCOUNT, key).label for e in entries if M.definition(e["platform"], M.ACCOUNT, key)), key)
        result.append(
            {
                "key": key,
                "label": label if len(platforms) == 1 else _shared_label(key),
                "comparable": comparable,
                "combined_value": combined,
                "combined_note": (
                    "Sum of the platform values above; each platform measures this differently (see definitions)."
                    if combined is not None
                    else None
                ),
                "platforms": entries,
            }
        )
    return result


def _shared_label(key: str) -> str:
    return {
        "followers": "Followers",
        "reach": "Reach / unique viewers",
        "views": "Views",
        "engagements": "Engagements (platform definitions differ)",
        "likes": "Likes",
        "comments": "Comments",
        "shares": "Shares",
        "saves": "Saves",
        "video_views": "Video views",
        "follows": "New follows",
        "unfollows": "Unfollows",
    }.get(key, key.replace("_", " ").capitalize())


def _reason_text(note: str) -> str:
    if note.startswith("missing_permission:"):
        scope = note.split(":", 1)[1]
        return f"The {scope} permission was not granted when the account was connected. Reconnect Meta to collect insights."
    return {
        "not_returned": "Meta did not return this metric for the account (it may require more followers or more data).",
        "unsupported_metric": "Meta does not support this metric for this account or API version.",
        "insufficient_data": "Meta does not report insights below its minimum audience thresholds.",
        "permission": "Meta denied access to insights for this account.",
        "token_expired": "The account authorization expired. Reconnect the account.",
    }.get(note, note.replace("_", " "))


def follower_growth(db: DBSession, filters: AnalyticsFilters) -> list[dict[str, Any]]:
    rows = _snapshots(db, filters.account_ids, ("followers",), filters.start, filters.end)
    by_account: dict[UUID, list[tuple[date, float | None]]] = defaultdict(list)
    for row in rows:
        by_account[row.social_account_id].append((row.snapshot_date, row.metric_value))
    result = []
    for account in filters.accounts:
        points = by_account.get(account.id, [])
        result.append(
            {
                "social_account_id": account.id,
                "account_name": account.display_name,
                "platform": account.platform,
                "change": C.follower_change(points),
                "snapshots": len(points),
                "latest": max(points, key=lambda item: item[0])[1] if points else None,
                "note": None if len(points) >= 2 else "At least two daily follower snapshots are needed to calculate growth.",
            }
        )
    return result


def timeseries(db: DBSession, filters: AnalyticsFilters, key: str, group_by: str = "platform") -> dict[str, Any]:
    rows = _snapshots(db, filters.account_ids, (key,), filters.start, filters.end)
    days = [filters.start + timedelta(days=offset) for offset in range(filters.days)]
    series: dict[str, dict[str, Any]] = {}
    for account in filters.accounts:
        definition = M.definition(account.platform, M.ACCOUNT, key)
        group_key = account.platform if group_by == "platform" else str(account.id)
        if group_key not in series:
            series[group_key] = {
                "key": group_key,
                "label": M.PLATFORM_LABELS[account.platform] if group_by == "platform" else account.display_name,
                "platform": account.platform,
                "metric_label": definition.label if definition else key,
                "definition": definition.definition if definition else M.NOT_SUPPORTED.get(account.platform, {}).get(key),
                "source_metric": definition.source_name if definition else None,
                "unit": definition.unit if definition else "count",
                "supported": definition is not None,
                "values": {day: None for day in days},
            }
    for row in rows:
        group_key = row.platform if group_by == "platform" else str(row.social_account_id)
        entry = series.get(group_key)
        if entry is None or row.metric_value is None or row.snapshot_date not in entry["values"]:
            continue
        current = entry["values"][row.snapshot_date]
        entry["values"][row.snapshot_date] = row.metric_value if current is None else current + row.metric_value
    output = []
    for entry in series.values():
        points = [{"date": day, "value": entry["values"][day]} for day in days]
        output.append({**{k: v for k, v in entry.items() if k != "values"}, "points": points, "has_data": any(p["value"] is not None for p in points)})
    return {"metric": key, "group_by": group_by, "start": filters.start, "end": filters.end, "series": output}


# Accounts -----------------------------------------------------------------------


def sync_status_for(db: DBSession, account: SocialAccount) -> dict[str, Any]:
    latest = last_job(db, account.id)
    success = last_job(db, account.id, statuses=("succeeded", "partial"))
    eligibility = analytics_eligibility(account)
    return {
        "social_account_id": account.id,
        "account_name": account.display_name,
        "platform": account.platform,
        "connection_status": account.connection_status,
        "last_synced_at": _utc(success.completed_at) if success else None,
        "last_sync_status": latest.status if latest else None,
        "last_error": latest.last_error if latest and latest.status == "failed" else None,
        "last_error_category": latest.error_category if latest and latest.status == "failed" else None,
        "next_attempt_at": _utc(latest.next_attempt_at) if latest and latest.status == "pending" else None,
        "active_job_id": latest.id if latest and latest.status in {"pending", "running"} else None,
        "insights_available": eligibility["insights_available"],
        "can_sync": eligibility["can_sync"],
        "missing_permissions": eligibility["missing_permissions"],
        "notes": eligibility["reasons"],
    }


def account_insights(db: DBSession, filters: AnalyticsFilters) -> list[dict[str, Any]]:
    result = []
    for account in filters.accounts:
        single = AnalyticsFilters(
            workspace_id=filters.workspace_id, start=filters.start, end=filters.end, accounts=[account], social_account_id=account.id
        )
        keys = tuple(metric.key for metric in M.account_metrics(account.platform))
        metrics = account_metric_summary(db, single, keys)
        flattened = []
        for metric in metrics:
            entry = metric["platforms"][0] if metric["platforms"] else None
            if entry is None:
                continue
            flattened.append({"key": metric["key"], "label": M.definition(account.platform, M.ACCOUNT, metric["key"]).label, **{k: v for k, v in entry.items() if k not in {"platform", "platform_label"}}})
        follower_series = timeseries(db, single, "followers", group_by="account")["series"]
        growth = follower_growth(db, single)
        result.append(
            {
                "account": {
                    "id": account.id,
                    "display_name": account.display_name,
                    "username": account.username,
                    "platform": account.platform,
                    "platform_label": M.PLATFORM_LABELS[account.platform],
                    "brand_id": account.brand_id,
                    "profile_image_url": account.profile_image_url,
                    "connection_status": account.connection_status,
                },
                "metrics": flattened,
                "follower_series": follower_series[0]["points"] if follower_series else [],
                "follower_change": growth[0]["change"] if growth else None,
                "sync": sync_status_for(db, account),
            }
        )
    return result


# Posts --------------------------------------------------------------------------


def post_to_dict(row: PostAnalytics, account: SocialAccount | None, project_title: str | None = None) -> dict[str, Any]:
    metrics = {key: getattr(row, key) for key in M.POST_COLUMNS}
    extras = row.raw_metrics.get("normalized_extras") if isinstance(row.raw_metrics, dict) else None
    availability = dict(row.metric_availability or {})
    for key, reason in M.NOT_SUPPORTED.get(row.platform, {}).items():
        if key in M.POST_COLUMNS and metrics.get(key) is None:
            availability.setdefault(key, "not_supported_on_platform")
    rate = C.engagement_rate(row.engagements, row.reach)
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "brand_id": row.brand_id,
        "social_account_id": row.social_account_id,
        "account_name": account.display_name if account else None,
        "platform": row.platform,
        "platform_label": M.PLATFORM_LABELS.get(row.platform, row.platform),
        "publication_id": row.publication_id,
        "project_id": row.project_id,
        "project_title": project_title,
        "draft_id": row.draft_id,
        "external_post_id": row.external_post_id,
        "permalink": row.permalink,
        "published_at": _utc(row.published_at),
        "content_format": row.content_format,
        "content_format_label": POST_FORMAT_LABELS.get(row.content_format or "", row.content_format),
        "caption_preview": row.caption_preview,
        "thumbnail_url": row.thumbnail_url,
        "metrics": metrics,
        "extra_metrics": extras if isinstance(extras, dict) else {},
        "metric_availability": availability,
        "engagement_rate": rate,
        "engagement_rate_note": (
            None
            if rate is not None
            else "Not calculated: reach or engagements are unavailable, or reach is zero."
        ),
        "engagement_definition": C.PLATFORM_ENGAGEMENT_DEFINITION.get(row.platform),
        "reach_definition": C.PLATFORM_REACH_DEFINITION.get(row.platform),
        "source": "autowok" if row.publication_id else "external",
        "collected_at": _utc(row.collected_at),
        "api_version": row.api_version,
    }


def _post_query(db: DBSession, filters: AnalyticsFilters, *, published_only_in_range: bool = True):
    query = db.query(PostAnalytics).filter(PostAnalytics.workspace_id == filters.workspace_id)
    if filters.social_account_id or filters.platform or filters.brand_id:
        query = query.filter(PostAnalytics.social_account_id.in_(filters.account_ids or [UUID(int=0)]))
    if filters.brand_id:
        query = query.filter(PostAnalytics.brand_id == filters.brand_id)
    if published_only_in_range:
        start = datetime(filters.start.year, filters.start.month, filters.start.day, tzinfo=timezone.utc)
        end = datetime(filters.end.year, filters.end.month, filters.end.day, tzinfo=timezone.utc) + timedelta(days=1)
        query = query.filter(PostAnalytics.published_at >= start, PostAnalytics.published_at < end)
    return query


def _project_titles(db: DBSession, rows: list[PostAnalytics]) -> dict[UUID, str]:
    ids = {row.project_id for row in rows if row.project_id}
    if not ids:
        return {}
    return {project.id: project.title for project in db.query(ContentProject).filter(ContentProject.id.in_(list(ids))).all()}


def _accounts_by_id(db: DBSession, workspace_id: UUID) -> dict[UUID, SocialAccount]:
    return {account.id: account for account in db.query(SocialAccount).filter(SocialAccount.workspace_id == workspace_id).all()}


def list_posts(
    db: DBSession,
    filters: AnalyticsFilters,
    *,
    content_format: str | None = None,
    source: str | None = None,
    min_engagements: int | None = None,
    max_engagements: int | None = None,
    sort: str = "published_at",
    order: str = "desc",
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    query = _post_query(db, filters)
    if content_format:
        query = query.filter(PostAnalytics.content_format == content_format)
    if source == "autowok":
        query = query.filter(PostAnalytics.publication_id.is_not(None))
    elif source == "external":
        query = query.filter(PostAnalytics.publication_id.is_(None))
    if min_engagements is not None:
        query = query.filter(PostAnalytics.engagements >= min_engagements)
    if max_engagements is not None:
        query = query.filter(PostAnalytics.engagements <= max_engagements)
    total = query.count()
    column = getattr(PostAnalytics, sort if sort in {"published_at", *M.POST_COLUMNS} else "published_at")
    direction = column.desc() if order == "desc" else column.asc()
    rows = query.order_by(direction.nulls_last(), PostAnalytics.published_at.desc()).offset(offset).limit(limit).all()
    accounts = _accounts_by_id(db, filters.workspace_id)
    titles = _project_titles(db, rows)
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [post_to_dict(row, accounts.get(row.social_account_id), titles.get(row.project_id)) for row in rows],
    }


def post_detail(db: DBSession, workspace_id: UUID, post_id: UUID) -> dict[str, Any] | None:
    row = db.query(PostAnalytics).filter(PostAnalytics.id == post_id, PostAnalytics.workspace_id == workspace_id).first()
    if row is None:
        return None
    account = db.get(SocialAccount, row.social_account_id)
    titles = _project_titles(db, [row])
    data = post_to_dict(row, account, titles.get(row.project_id))
    data["history"] = [
        {"snapshot_date": entry.snapshot_date, "collected_at": _utc(entry.collected_at), "metrics": dict(entry.metrics or {})}
        for entry in row.history
    ]
    data["definitions"] = [metric.to_dict() for metric in M.post_metrics(row.platform, row.content_format)]
    return data


def compare_posts(db: DBSession, workspace_id: UUID, post_ids: list[UUID]) -> dict[str, Any]:
    rows = db.query(PostAnalytics).filter(PostAnalytics.workspace_id == workspace_id, PostAnalytics.id.in_(post_ids)).all()
    accounts = _accounts_by_id(db, workspace_id)
    titles = _project_titles(db, rows)
    by_id = {row.id: row for row in rows}
    ordered = [by_id[post_id] for post_id in post_ids if post_id in by_id]
    posts = [post_to_dict(row, accounts.get(row.social_account_id), titles.get(row.project_id)) for row in ordered]
    platforms = {row.platform for row in ordered}
    comparison = []
    for key in POST_SUMMARY_KEYS:
        comparable = len(platforms) <= 1 or M.is_comparable(M.POST, key)
        comparison.append(
            {
                "key": key,
                "label": _shared_label(key),
                "comparable": comparable,
                "note": None if comparable else "Definitions differ between Facebook and Instagram; compare within one platform.",
                "values": [{"post_id": post["id"], "value": post["metrics"].get(key), "availability": post["metric_availability"].get(key)} for post in posts],
                "definitions": {platform: (M.definition(platform, M.POST, key).definition if M.definition(platform, M.POST, key) else M.NOT_SUPPORTED.get(platform, {}).get(key)) for platform in sorted(platforms)},
            }
        )
    comparison.append(
        {
            "key": "engagement_rate",
            "label": M.DERIVED_METRICS["engagement_rate_by_reach"]["label"],
            "comparable": len(platforms) <= 1,
            "note": M.DERIVED_METRICS["engagement_rate_by_reach"]["definition"],
            "values": [{"post_id": post["id"], "value": post["engagement_rate"], "availability": None if post["engagement_rate"] is not None else "not_calculated"} for post in posts],
            "definitions": {},
        }
    )
    return {"posts": posts, "metrics": comparison, "mixed_platforms": len(platforms) > 1}


def published_post_counts(db: DBSession, filters: AnalyticsFilters) -> dict[str, Any]:
    rows = _post_query(db, filters).with_entities(PostAnalytics.platform, func.count(PostAnalytics.id)).group_by(PostAnalytics.platform).all()
    by_platform = {platform: count for platform, count in rows}
    autowok = _post_query(db, filters).filter(PostAnalytics.publication_id.is_not(None)).count()
    previous_start, previous_end = filters.previous
    previous = _post_query(db, AnalyticsFilters(filters.workspace_id, previous_start, previous_end, filters.brand_id, filters.platform, filters.social_account_id, filters.accounts)).count()
    total = sum(by_platform.values())
    return {"total": total, "by_platform": by_platform, "from_autowok": autowok, "previous_total": previous, "change_percent": C.percentage_change(total, previous)}


def top_posts(db: DBSession, filters: AnalyticsFilters, *, limit: int = 5, metric: str = "engagements") -> list[dict[str, Any]]:
    rows = _post_query(db, filters).all()
    accounts = _accounts_by_id(db, filters.workspace_id)
    titles = _project_titles(db, rows)
    posts = [post_to_dict(row, accounts.get(row.social_account_id), titles.get(row.project_id)) for row in rows]
    flat = [{**post, metric: post["metrics"].get(metric) if metric != "engagement_rate" else post["engagement_rate"]} for post in posts]
    return [{k: v for k, v in item.items() if k != metric or k in {"engagement_rate"}} for item in C.rank(flat, metric)[:limit]]


# Overview and comparisons -------------------------------------------------------


def overview(db: DBSession, filters: AnalyticsFilters) -> dict[str, Any]:
    metrics = account_metric_summary(db, filters, OVERVIEW_KEYS)
    collected = [entry["collected_at"] for metric in metrics for entry in metric["platforms"] if entry.get("collected_at")]
    return {
        "filters": filters.to_dict(),
        "accounts": [sync_status_for(db, account) for account in filters.accounts],
        "metrics": metrics,
        "follower_growth": follower_growth(db, filters),
        "published_posts": published_post_counts(db, filters),
        "top_posts": top_posts(db, filters, limit=5),
        "freshness": {
            "newest_collected_at": max(collected) if collected else None,
            "oldest_collected_at": min(collected) if collected else None,
        },
        "notes": [
            "Totals are shown per platform. Facebook and Instagram define reach, views and engagement differently; see each metric's definition.",
            "A missing value means Meta did not provide the metric for the period; it is never shown as zero.",
        ],
    }


def platform_comparison(db: DBSession, filters: AnalyticsFilters) -> dict[str, Any]:
    account_keys = ("followers", "reach", "views", "engagements", "likes", "comments", "shares", "saves")
    account_metrics = account_metric_summary(db, filters, account_keys)
    rows = _post_query(db, filters).all()
    per_platform_posts: dict[str, list[PostAnalytics]] = defaultdict(list)
    for row in rows:
        per_platform_posts[row.platform].append(row)
    platforms = sorted({account.platform for account in filters.accounts}, key=M.PLATFORMS.index)
    post_metrics = []
    for key in POST_SUMMARY_KEYS:
        entries = []
        for platform in platforms:
            definition = M.definition(platform, M.POST, key)
            values = [getattr(row, key) for row in per_platform_posts.get(platform, [])]
            total, available, count = C.sum_available(values)
            entries.append(
                {
                    "platform": platform,
                    "platform_label": M.PLATFORM_LABELS[platform],
                    "total": total,
                    "average_per_post": C.mean(values),
                    "posts_with_data": available,
                    "posts_total": count,
                    "definition": definition.definition if definition else M.NOT_SUPPORTED.get(platform, {}).get(key, "Not reported by this platform."),
                    "source_metric": definition.source_name if definition else None,
                    "availability": "not_supported" if definition is None else ("available" if available == count and count > 0 else "partial" if available else "unavailable"),
                }
            )
        comparable = M.is_comparable(M.POST, key)
        post_metrics.append(
            {
                "key": key,
                "label": _shared_label(key),
                "comparable": comparable,
                "note": None if comparable else "Not directly comparable: the platforms count different interactions or do not report this metric.",
                "platforms": entries,
            }
        )
    rates = []
    for platform in platforms:
        values = [C.engagement_rate(row.engagements, row.reach) for row in per_platform_posts.get(platform, [])]
        rates.append(
            {
                "platform": platform,
                "platform_label": M.PLATFORM_LABELS[platform],
                "average_engagement_rate": C.mean(values),
                "posts_with_rate": sum(1 for value in values if value is not None),
                "posts_total": len(values),
                "engagement_definition": C.PLATFORM_ENGAGEMENT_DEFINITION[platform],
                "reach_definition": C.PLATFORM_REACH_DEFINITION[platform],
            }
        )
    return {
        "filters": filters.to_dict(),
        "platforms": [{"key": platform, "label": M.PLATFORM_LABELS[platform], "accounts": sum(1 for a in filters.accounts if a.platform == platform)} for platform in platforms],
        "account_metrics": account_metrics,
        "post_metrics": post_metrics,
        "engagement_rates": rates,
        "meaningful": len(platforms) == 2,
        "note": (
            "Only metrics marked comparable measure the same thing on both platforms. Engagement rates use each platform's own definitions and are shown side by side, not combined."
            if len(platforms) == 2
            else "Connect accounts on both platforms, or remove the platform filter, to compare Facebook and Instagram."
        ),
    }


def content_performance(db: DBSession, filters: AnalyticsFilters) -> dict[str, Any]:
    rows = _post_query(db, filters).all()
    accounts = _accounts_by_id(db, filters.workspace_id)
    titles = _project_titles(db, rows)
    posts = [post_to_dict(row, accounts.get(row.social_account_id), titles.get(row.project_id)) for row in rows]
    with_rate = [post for post in posts if post["engagement_rate"] is not None]
    with_engagements = [post for post in posts if post["metrics"].get("engagements") is not None]
    if len(with_rate) >= MIN_RANKING_SAMPLE and len(with_rate) >= len(with_engagements) // 2:
        ranking_metric = "engagement_rate"
        ranked = C.rank([{**post, "engagement_rate": post["engagement_rate"]} for post in with_rate], "engagement_rate")
        method = "Ranked by engagement rate by reach (platform-specific definitions); posts without reach are excluded."
    else:
        ranking_metric = "engagements"
        ranked = C.rank([{**post, "engagements": post["metrics"].get("engagements")} for post in with_engagements], "engagements")
        method = "Ranked by engagements (platform-specific definitions) because reach is unavailable for most posts."
    ranked = [{k: v for k, v in item.items() if k != "engagements"} for item in ranked]
    top = ranked[:5]
    bottom = list(reversed(ranked[-5:])) if len(ranked) > 5 else []

    by_format: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for post in posts:
        by_format[f"{post['platform']}:{post['content_format'] or 'unknown'}"].append(post)
    formats = []
    for key, items in sorted(by_format.items()):
        platform, content_format = key.split(":", 1)
        engagement_values = [post["metrics"].get("engagements") for post in items]
        reach_values = [post["metrics"].get("reach") for post in items]
        rate_values = [post["engagement_rate"] for post in items]
        formats.append(
            {
                "platform": platform,
                "platform_label": M.PLATFORM_LABELS.get(platform, platform),
                "content_format": content_format,
                "content_format_label": POST_FORMAT_LABELS.get(content_format, content_format),
                "posts": len(items),
                "average_engagements": C.mean(engagement_values),
                "average_reach": C.mean(reach_values),
                "average_engagement_rate": C.mean(rate_values),
                "enough_data": len(items) >= MIN_FORMAT_SAMPLE,
                "note": None if len(items) >= MIN_FORMAT_SAMPLE else f"Fewer than {MIN_FORMAT_SAMPLE} posts; averages are indicative only.",
            }
        )
    best_format = None
    eligible_formats = [entry for entry in formats if entry["enough_data"] and entry["average_engagement_rate"] is not None]
    if eligible_formats:
        best_format = max(eligible_formats, key=lambda entry: entry["average_engagement_rate"])

    weeks: dict[date, dict[str, Any]] = {}
    cursor = filters.start
    while cursor <= filters.end:
        weeks[cursor] = {"week_start": cursor, "posts": 0, "engagements": None, "reach": None}
        cursor += timedelta(days=7)
    week_starts = sorted(weeks)
    for post in posts:
        published = post["published_at"]
        if published is None:
            continue
        day = published.date()
        bucket = max((start for start in week_starts if start <= day), default=None)
        if bucket is None:
            continue
        entry = weeks[bucket]
        entry["posts"] += 1
        for key in ("engagements", "reach"):
            value = post["metrics"].get(key)
            if value is not None:
                entry[key] = value if entry[key] is None else entry[key] + value
    previous_start, previous_end = filters.previous
    previous_rows = _post_query(db, AnalyticsFilters(filters.workspace_id, previous_start, previous_end, filters.brand_id, filters.platform, filters.social_account_id, filters.accounts)).all()
    current_total, _, _ = C.sum_available(row.engagements for row in rows)
    previous_total, _, _ = C.sum_available(row.engagements for row in previous_rows)
    published_days = [post["published_at"].date() for post in posts if post["published_at"]]
    return {
        "filters": filters.to_dict(),
        "post_count": len(posts),
        "ranking_metric": ranking_metric,
        "ranking_method": method,
        "top_posts": top,
        "bottom_posts": bottom,
        "formats": formats,
        "best_format": best_format,
        "best_format_note": (
            "Highest average engagement rate among formats with enough posts. This describes past measurements only; it does not predict future performance."
            if best_format
            else f"Not enough posts per format (at least {MIN_FORMAT_SAMPLE} with reach data) to identify a best-performing format."
        ),
        "weekly_trend": [weeks[start] for start in week_starts],
        "period_change": {
            "current_engagements": current_total,
            "previous_engagements": previous_total,
            "change_percent": C.percentage_change(current_total, previous_total),
            "current_posts": len(rows),
            "previous_posts": len(previous_rows),
        },
        "consistency": C.consistency(published_days, filters.start, filters.end),
        "notes": [
            "Rankings are deterministic calculations on measured values; they do not explain why a post performed as it did.",
            "Engagement definitions differ by platform (Facebook: reactions + comments + shares + clicks; Instagram: total interactions).",
        ],
    }


def brand_name(db: DBSession, brand_id: UUID | None) -> str | None:
    if brand_id is None:
        return None
    brand = db.get(Brand, brand_id)
    return brand.name if brand else None
