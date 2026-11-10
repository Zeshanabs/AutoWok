"""Meta Graph API data collection for analytics.

The collector turns Meta responses into normalized ``MetricValue`` and
``CollectedPost`` records. Responses are untrusted input: every value is type
checked and anything unexpected is recorded as *unavailable* rather than
guessed. Requests are chunked to Meta's documented limits (90 days per Page
Insights request; Instagram insights are requested in windows of at most 30
days) and paginated with bounded cursors.

The collector never logs or stores access tokens; it only receives them as
arguments and passes them to ``MetaGraphClient``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from app.core.config import get_settings
from app.services.analytics import errors as E
from app.services.analytics import metrics as M
from app.services.meta_graph import MetaGraphClient, MetaGraphError

logger = logging.getLogger("autowok.analytics")

UTC = timezone.utc
FACEBOOK_MAX_RANGE_DAYS = 90
INSTAGRAM_MAX_RANGE_DAYS = 30
PAGE_SIZE = 50
MAX_PAGES = 20

FACEBOOK_PAGE_FIELDS = "id,name,followers_count,fan_count"
INSTAGRAM_USER_FIELDS = "id,username,followers_count,media_count"
FACEBOOK_POST_FIELDS = (
    "id,created_time,permalink_url,status_type,full_picture,message,shares,"
    "comments.summary(total_count).limit(0),reactions.summary(total_count).limit(0),"
    "likes.summary(total_count).limit(0),attachments{media_type,type,target{id}}"
)
INSTAGRAM_MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,permalink,thumbnail_url,media_url,timestamp,like_count,comments_count"
)

FACEBOOK_POST_INSIGHTS = ("post_media_view", "post_total_media_view_unique", "post_clicks", "post_reactions_by_type_total")
FACEBOOK_VIDEO_POST_INSIGHTS = ("post_video_views",)
INSTAGRAM_FEED_INSIGHTS = ("reach", "views", "likes", "comments", "saved", "shares", "total_interactions", "follows", "profile_visits")
INSTAGRAM_REEL_INSIGHTS = (
    "reach", "views", "likes", "comments", "saved", "shares", "total_interactions",
    "ig_reels_avg_watch_time", "ig_reels_video_view_total_time",
)
INSTAGRAM_VIDEO_INSIGHTS = ("reach", "views", "likes", "comments", "saved", "shares", "total_interactions")

# Instagram account metrics that only support ``metric_type=total_value``.
INSTAGRAM_TOTAL_VALUE_METRICS = (
    "views", "accounts_engaged", "total_interactions", "likes", "comments", "shares", "saves", "replies", "profile_links_taps",
)

MISSING_PERMISSION = "missing_permission"
NOT_RETURNED = "not_returned"
NOT_APPLICABLE = "not_applicable"
NOT_SUPPORTED = "not_supported_on_platform"


@dataclass
class MetricValue:
    key: str
    source: str
    snapshot_date: date
    value: float | None
    unit: str = "count"
    breakdown: dict[str, Any] | None = None


@dataclass
class AccountCollection:
    platform: str
    snapshots: list[MetricValue] = field(default_factory=list)
    # normalized key -> reason
    unavailable: dict[str, str] = field(default_factory=dict)
    requests: int = 0


@dataclass
class CollectedPost:
    external_post_id: str
    platform: str
    permalink: str | None
    published_at: datetime | None
    content_format: str | None
    caption_preview: str | None
    thumbnail_url: str | None
    values: dict[str, float | None] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    availability: dict[str, str] = field(default_factory=dict)
    # Other Meta object ids that identify the same post (e.g. the video id of a
    # Facebook video post), used to link Autowok publications.
    alternate_ids: list[str] = field(default_factory=list)


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _parse_meta_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Meta uses "+0000" without a colon.
    if len(text) >= 5 and text[-5] in "+-" and text[-3] != ":":
        text = text[:-2] + ":" + text[-2:]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _preview(text: Any, limit: int = 280) -> str | None:
    if not isinstance(text, str):
        return None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def _unix(day: date, *, end_of_day: bool = False) -> int:
    moment = datetime(day.year, day.month, day.day, tzinfo=UTC)
    if end_of_day:
        moment += timedelta(days=1) - timedelta(seconds=1)
    return int(moment.timestamp())


def _chunks(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=max_days - 1))
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def facebook_format(post: dict[str, Any]) -> str:
    status_type = post.get("status_type")
    attachments = post.get("attachments")
    data = attachments.get("data") if isinstance(attachments, dict) else None
    first = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    attachment_type = first.get("type") if isinstance(first.get("type"), str) else ""
    media_type = first.get("media_type") if isinstance(first.get("media_type"), str) else ""
    if attachment_type == "album":
        return "multi_photo"
    if status_type == "added_video" or media_type == "video" or attachment_type.startswith("video"):
        return "video"
    if status_type == "added_photos" or media_type == "photo" or attachment_type == "photo":
        return "photo"
    if status_type in {"mobile_status_update", "status"} and not first:
        return "text"
    if status_type == "shared_story" or attachment_type in {"share", "link"} or media_type == "link":
        return "link"
    if not first:
        return "text"
    return "other"


def instagram_format(media: dict[str, Any]) -> str | None:
    product = media.get("media_product_type")
    media_type = media.get("media_type")
    if product == "REELS":
        return "reel"
    if product == "STORY":
        return "story"
    if media_type == "CAROUSEL_ALBUM":
        return "carousel"
    if media_type == "IMAGE":
        return "image"
    if media_type == "VIDEO":
        return "video"
    return None


class MetaInsightsCollector:
    def __init__(self, graph: MetaGraphClient) -> None:
        self._graph = graph
        self.api_version = get_settings().meta_graph_api_version

    # ----------------------------------------------------------- utilities

    def _get(self, path: str, token: str, **params: Any) -> dict[str, Any]:
        return self._graph.get(path, token, **{key: str(value) for key, value in params.items() if value is not None})

    def _insights_with_fallback(
        self,
        path: str,
        token: str,
        metrics: tuple[str, ...],
        params: dict[str, Any],
        collection_requests: list[int],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Request metrics together; on an unsupported-metric error, request
        them one by one so a single bad metric cannot hide the others.

        Returns ``(entries by metric name, unavailable reasons by metric name)``.
        Aborting failures (token, permission, rate limit, network) are raised.
        """
        entries: dict[str, Any] = {}
        unavailable: dict[str, str] = {}
        try:
            collection_requests[0] += 1
            body = self._get(path, token, metric=",".join(metrics), **params)
        except MetaGraphError as error:
            failure = E.classify_collection_error(error)
            if failure.aborts_sync:
                raise
            if failure.category != E.UNSUPPORTED_METRIC or len(metrics) == 1:
                for name in metrics:
                    unavailable[name] = failure.category
                return entries, unavailable
            for name in metrics:
                try:
                    collection_requests[0] += 1
                    single = self._get(path, token, metric=name, **params)
                except MetaGraphError as single_error:
                    single_failure = E.classify_collection_error(single_error)
                    if single_failure.aborts_sync:
                        raise
                    unavailable[name] = single_failure.category
                    continue
                entries.update(_entries_by_name(single))
        else:
            entries.update(_entries_by_name(body))
        for name in metrics:
            if name not in entries and name not in unavailable:
                unavailable[name] = NOT_RETURNED
        return entries, unavailable

    # ------------------------------------------------------------ Facebook

    def facebook_account(self, page_id: str, token: str, start: date, end: date, scopes: set[str]) -> AccountCollection:
        result = AccountCollection(platform=M.FACEBOOK)
        requests = [0]
        requests[0] += 1
        page = self._get(f"/{page_id}", token, fields=FACEBOOK_PAGE_FIELDS)
        followers = _to_number(page.get("followers_count"))
        if followers is None:
            followers = _to_number(page.get("fan_count"))
        if followers is not None:
            result.snapshots.append(MetricValue("followers", "followers_count", end, followers))
        else:
            result.unavailable["followers"] = NOT_RETURNED

        insight_metrics = [m for m in M.account_metrics(M.FACEBOOK) if m.source_kind == M.INSIGHT]
        if "read_insights" not in scopes:
            for metric in insight_metrics:
                result.unavailable[metric.key] = f"{MISSING_PERMISSION}:read_insights"
            result.requests = requests[0]
            return result

        names = tuple(metric.source_name for metric in insight_metrics)
        by_source = {metric.source_name: metric for metric in insight_metrics}
        for chunk_start, chunk_end in _chunks(start, end, FACEBOOK_MAX_RANGE_DAYS):
            entries, unavailable = self._insights_with_fallback(
                f"/{page_id}/insights",
                token,
                names,
                {"period": "day", "since": _unix(chunk_start), "until": _unix(chunk_end, end_of_day=True)},
                requests,
            )
            for name, reason in unavailable.items():
                result.unavailable.setdefault(by_source[name].key, reason)
            for name, entry in entries.items():
                metric = by_source.get(name)
                if metric is None:
                    continue
                for value_entry in _values(entry):
                    end_time = _parse_meta_datetime(value_entry.get("end_time"))
                    if end_time is None:
                        continue
                    # Meta's ``end_time`` marks the end of the day period; the
                    # value describes the day that ended then.
                    snapshot_day = (end_time - timedelta(days=1)).date()
                    if snapshot_day < chunk_start - timedelta(days=1) or snapshot_day > chunk_end:
                        continue
                    number, breakdown = _number_and_breakdown(value_entry.get("value"))
                    if number is None:
                        continue
                    result.snapshots.append(MetricValue(metric.key, name, snapshot_day, number, metric.unit, breakdown))
        result.requests = requests[0]
        return result

    def facebook_posts(self, page_id: str, token: str, since: datetime, limit: int) -> list[dict[str, Any]]:
        return self._paginate(
            f"/{page_id}/published_posts",
            token,
            {"fields": FACEBOOK_POST_FIELDS, "since": int(since.timestamp()), "limit": PAGE_SIZE},
            limit,
        )

    def facebook_post(self, post_id: str, token: str) -> dict[str, Any]:
        return self._get(f"/{post_id}", token, fields=FACEBOOK_POST_FIELDS)

    def facebook_post_metrics(self, post: dict[str, Any], token: str, scopes: set[str]) -> CollectedPost:
        post_id = str(post.get("id"))
        content_format = facebook_format(post)
        collected = CollectedPost(
            external_post_id=post_id,
            platform=M.FACEBOOK,
            permalink=post.get("permalink_url") if isinstance(post.get("permalink_url"), str) else None,
            published_at=_parse_meta_datetime(post.get("created_time")),
            content_format=content_format,
            caption_preview=_preview(post.get("message")),
            thumbnail_url=post.get("full_picture") if isinstance(post.get("full_picture"), str) else None,
        )
        attachments = post.get("attachments")
        data = attachments.get("data") if isinstance(attachments, dict) else None
        if isinstance(data, list):
            for item in data:
                target = item.get("target") if isinstance(item, dict) else None
                target_id = target.get("id") if isinstance(target, dict) else None
                if isinstance(target_id, str) and target_id and target_id != post_id:
                    collected.alternate_ids.append(target_id)

        # Object fields -------------------------------------------------
        comments = _summary_count(post.get("comments"))
        if comments is not None:
            collected.values["comments"] = comments
            collected.raw["comments.summary.total_count"] = comments
        else:
            collected.availability["comments"] = NOT_RETURNED
        shares = post.get("shares")
        share_count = _to_number(shares.get("count")) if isinstance(shares, dict) else None
        if share_count is not None:
            collected.values["shares"] = share_count
            collected.raw["shares.count"] = share_count
        else:
            # Meta omits ``shares`` when a post has never been shared.
            collected.values["shares"] = 0.0
            collected.raw["shares.count"] = None
            collected.raw["shares_note"] = "absent_field_treated_as_zero"
        reactions_total = _summary_count(post.get("reactions"))
        likes_total = _summary_count(post.get("likes"))
        if reactions_total is not None:
            collected.raw["reactions.summary.total_count"] = reactions_total
        if likes_total is not None:
            collected.raw["likes.summary.total_count"] = likes_total

        # Insights ------------------------------------------------------
        if "read_insights" not in scopes:
            for key in ("views", "reach", "clicks", "video_views"):
                collected.availability[key] = f"{MISSING_PERMISSION}:read_insights"
            entries: dict[str, Any] = {}
            unavailable: dict[str, str] = {}
        else:
            names = FACEBOOK_POST_INSIGHTS + (FACEBOOK_VIDEO_POST_INSIGHTS if content_format == "video" else ())
            entries, unavailable = self._insights_with_fallback(
                f"/{post_id}/insights", token, names, {"period": "lifetime"}, [0]
            )
        lifetime = {name: _lifetime_value(entry) for name, entry in entries.items()}
        for name, (number, breakdown) in lifetime.items():
            collected.raw[name] = breakdown if breakdown is not None else number

        def take(key: str, source: str) -> None:
            if source in lifetime and lifetime[source][0] is not None:
                collected.values[key] = lifetime[source][0]
            elif source in unavailable:
                collected.availability[key] = unavailable[source]
            elif key not in collected.availability:
                collected.availability[key] = NOT_RETURNED

        take("views", "post_media_view")
        take("reach", "post_total_media_view_unique")
        take("clicks", "post_clicks")
        if content_format == "video":
            take("video_views", "post_video_views")
        else:
            collected.availability["video_views"] = NOT_APPLICABLE

        reactions_number, reactions_breakdown = lifetime.get("post_reactions_by_type_total", (None, None))
        if reactions_breakdown is not None:
            like_value = _to_number(reactions_breakdown.get("like"))
            collected.values["reactions"] = reactions_number
            collected.values["likes"] = like_value if like_value is not None else 0.0
        elif reactions_number is not None:
            collected.values["reactions"] = reactions_number
            if likes_total is not None:
                collected.values["likes"] = likes_total
            else:
                collected.availability["likes"] = NOT_RETURNED
        else:
            if reactions_total is not None:
                collected.values["reactions"] = reactions_total
                collected.availability["reactions"] = "from_reactions_summary"
            else:
                collected.availability["reactions"] = unavailable.get("post_reactions_by_type_total", NOT_RETURNED)
            if likes_total is not None:
                collected.values["likes"] = likes_total
                collected.availability["likes"] = "from_likes_summary"
            else:
                collected.availability["likes"] = unavailable.get("post_reactions_by_type_total", NOT_RETURNED)
        collected.availability["saves"] = NOT_SUPPORTED

        # Derived engagements (documented in metrics.DERIVED/POST_METRICS).
        parts = [collected.values.get("reactions"), collected.values.get("comments"), collected.values.get("shares")]
        if all(part is not None for part in parts):
            total = float(sum(part for part in parts if part is not None))
            clicks = collected.values.get("clicks")
            if clicks is not None:
                collected.values["engagements"] = total + clicks
                collected.availability["engagements"] = "calculated"
            else:
                collected.values["engagements"] = total
                collected.availability["engagements"] = "calculated_without_clicks"
        else:
            collected.availability["engagements"] = NOT_RETURNED
        return collected

    # ----------------------------------------------------------- Instagram

    def instagram_account(self, ig_id: str, token: str, start: date, end: date, scopes: set[str]) -> AccountCollection:
        result = AccountCollection(platform=M.INSTAGRAM)
        requests = [0]
        requests[0] += 1
        user = self._get(f"/{ig_id}", token, fields=INSTAGRAM_USER_FIELDS)
        followers = _to_number(user.get("followers_count"))
        if followers is not None:
            result.snapshots.append(MetricValue("followers", "followers_count", end, followers))
        else:
            result.unavailable["followers"] = NOT_RETURNED

        insight_metrics = [m for m in M.account_metrics(M.INSTAGRAM) if m.source_kind == M.INSIGHT]
        by_source = {metric.source_name: metric for metric in insight_metrics}
        if "instagram_manage_insights" not in scopes:
            for metric in insight_metrics:
                result.unavailable[metric.key] = f"{MISSING_PERMISSION}:instagram_manage_insights"
            result.requests = requests[0]
            return result

        # ``reach`` supports a daily time series.
        for chunk_start, chunk_end in _chunks(start, end, INSTAGRAM_MAX_RANGE_DAYS):
            entries, unavailable = self._insights_with_fallback(
                f"/{ig_id}/insights",
                token,
                ("reach",),
                {
                    "period": "day",
                    "metric_type": "time_series",
                    "since": _unix(chunk_start),
                    "until": _unix(chunk_end, end_of_day=True),
                },
                requests,
            )
            if "reach" in unavailable:
                result.unavailable.setdefault("reach", unavailable["reach"])
            for value_entry in _values(entries.get("reach", {})):
                end_time = _parse_meta_datetime(value_entry.get("end_time"))
                number = _to_number(value_entry.get("value"))
                if end_time is None or number is None:
                    continue
                snapshot_day = (end_time - timedelta(days=1)).date()
                if snapshot_day < chunk_start - timedelta(days=1) or snapshot_day > chunk_end:
                    continue
                result.snapshots.append(MetricValue("reach", "reach", snapshot_day, number))

        # The remaining metrics only support ``total_value``: one request per day.
        day = start
        total_names = tuple(name for name in INSTAGRAM_TOTAL_VALUE_METRICS if name in by_source)
        while day <= end:
            entries, unavailable = self._insights_with_fallback(
                f"/{ig_id}/insights",
                token,
                total_names,
                {
                    "period": "day",
                    "metric_type": "total_value",
                    "since": _unix(day),
                    "until": _unix(day, end_of_day=True),
                },
                requests,
            )
            for name, reason in unavailable.items():
                result.unavailable.setdefault(by_source[name].key, reason)
            for name, entry in entries.items():
                metric = by_source.get(name)
                total = entry.get("total_value") if isinstance(entry, dict) else None
                number = _to_number(total.get("value")) if isinstance(total, dict) else None
                if metric is None or number is None:
                    continue
                result.snapshots.append(MetricValue(metric.key, name, day, number, metric.unit))
            day += timedelta(days=1)
        result.requests = requests[0]
        return result

    def instagram_media(self, ig_id: str, token: str, since: datetime, limit: int) -> list[dict[str, Any]]:
        return self._paginate(
            f"/{ig_id}/media",
            token,
            {"fields": INSTAGRAM_MEDIA_FIELDS, "since": int(since.timestamp()), "limit": PAGE_SIZE},
            limit,
        )

    def instagram_media_item(self, media_id: str, token: str) -> dict[str, Any]:
        return self._get(f"/{media_id}", token, fields=INSTAGRAM_MEDIA_FIELDS)

    def instagram_media_metrics(self, media: dict[str, Any], token: str, scopes: set[str]) -> CollectedPost:
        media_id = str(media.get("id"))
        content_format = instagram_format(media)
        thumbnail = media.get("thumbnail_url") if isinstance(media.get("thumbnail_url"), str) else None
        if thumbnail is None and isinstance(media.get("media_url"), str) and content_format in {"image", "carousel"}:
            thumbnail = media["media_url"]
        collected = CollectedPost(
            external_post_id=media_id,
            platform=M.INSTAGRAM,
            permalink=media.get("permalink") if isinstance(media.get("permalink"), str) else None,
            published_at=_parse_meta_datetime(media.get("timestamp")),
            content_format=content_format,
            caption_preview=_preview(media.get("caption")),
            thumbnail_url=thumbnail,
        )
        like_count = _to_number(media.get("like_count"))
        comments_count = _to_number(media.get("comments_count"))
        if like_count is not None:
            collected.values["likes"] = like_count
            collected.raw["like_count"] = like_count
        else:
            collected.availability["likes"] = "hidden_or_not_returned"
        if comments_count is not None:
            collected.values["comments"] = comments_count
            collected.raw["comments_count"] = comments_count
        else:
            collected.availability["comments"] = NOT_RETURNED
        for key, reason in M.NOT_SUPPORTED[M.INSTAGRAM].items():
            if key in M.POST_COLUMNS:
                collected.availability[key] = NOT_SUPPORTED

        insight_keys = ("reach", "views", "saves", "shares", "engagements")
        if content_format in {None, "story"}:
            for key in insight_keys:
                collected.availability[key] = NOT_APPLICABLE
            return collected
        if "instagram_manage_insights" not in scopes:
            for key in insight_keys:
                collected.availability[key] = f"{MISSING_PERMISSION}:instagram_manage_insights"
            return collected

        names = {
            "reel": INSTAGRAM_REEL_INSIGHTS,
            "video": INSTAGRAM_VIDEO_INSIGHTS,
        }.get(content_format, INSTAGRAM_FEED_INSIGHTS)
        entries, unavailable = self._insights_with_fallback(f"/{media_id}/insights", token, names, {}, [0])
        lifetime = {name: _lifetime_value(entry)[0] for name, entry in entries.items()}
        for name, number in lifetime.items():
            collected.raw[name] = number
        mapping = {
            "reach": "reach",
            "views": "views",
            "saves": "saved",
            "shares": "shares",
            "engagements": "total_interactions",
            "follows": "follows",
            "profile_visits": "profile_visits",
            "reel_avg_watch_time": "ig_reels_avg_watch_time",
            "reel_total_watch_time": "ig_reels_video_view_total_time",
        }
        for key, source in mapping.items():
            if source not in names:
                continue
            if source in lifetime and lifetime[source] is not None:
                collected.values[key] = lifetime[source]
            else:
                collected.availability[key] = unavailable.get(source, NOT_RETURNED)
        if collected.values.get("engagements") is None:
            parts = [collected.values.get(k) for k in ("likes", "comments", "saves", "shares")]
            if all(part is not None for part in parts):
                collected.values["engagements"] = float(sum(part for part in parts if part is not None))
                collected.availability["engagements"] = "calculated_from_likes_comments_saves_shares"
        return collected

    # ---------------------------------------------------------- pagination

    def _paginate(self, path: str, token: str, params: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        after: str | None = None
        for _ in range(MAX_PAGES):
            query = dict(params)
            if after:
                query["after"] = after
            body = self._get(path, token, **query)
            data = body.get("data")
            if not isinstance(data, list):
                break
            items.extend(item for item in data if isinstance(item, dict) and isinstance(item.get("id"), (str, int)))
            if len(items) >= limit:
                return items[:limit]
            paging = body.get("paging")
            cursors = paging.get("cursors") if isinstance(paging, dict) else None
            next_cursor = cursors.get("after") if isinstance(cursors, dict) else None
            has_next = isinstance(paging, dict) and isinstance(paging.get("next"), str)
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor == after or not has_next:
                break
            after = next_cursor
        return items[:limit]


# ----------------------------------------------------------------- parsing


def _entries_by_name(body: dict[str, Any]) -> dict[str, Any]:
    data = body.get("data")
    entries: dict[str, Any] = {}
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                entries[entry["name"]] = entry
    return entries


def _values(entry: Any) -> list[dict[str, Any]]:
    values = entry.get("values") if isinstance(entry, dict) else None
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _number_and_breakdown(value: Any) -> tuple[float | None, dict[str, Any] | None]:
    number = _to_number(value)
    if number is not None:
        return number, None
    if isinstance(value, dict):
        numbers = {key: _to_number(item) for key, item in value.items() if isinstance(key, str)}
        clean = {key: item for key, item in numbers.items() if item is not None}
        if clean:
            return float(sum(clean.values())), clean
        if not value:
            return 0.0, {}
    return None, None


def _lifetime_value(entry: Any) -> tuple[float | None, dict[str, Any] | None]:
    for item in _values(entry):
        number, breakdown = _number_and_breakdown(item.get("value"))
        if number is not None:
            return number, breakdown
    total = entry.get("total_value") if isinstance(entry, dict) else None
    if isinstance(total, dict):
        return _number_and_breakdown(total.get("value"))
    return None, None


def _summary_count(edge: Any) -> float | None:
    summary = edge.get("summary") if isinstance(edge, dict) else None
    return _to_number(summary.get("total_count")) if isinstance(summary, dict) else None


GraphFactory = Callable[[], MetaGraphClient]
