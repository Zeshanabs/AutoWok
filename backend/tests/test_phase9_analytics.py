"""Phase 9: analytics collection, storage, calculations, API and reports (mocked Meta)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest

from app.models import ContentPublication, SocialAccount
from app.models.analytics import AnalyticsSnapshot, AnalyticsSyncJob, PostAnalytics
from app.services.analytics import calculations as C
from app.services.analytics import errors as E
from app.services.analytics import metrics as M
from app.services.analytics.collector import facebook_format, instagram_format
from app.services.analytics.sync import (
    SyncConflict,
    due_sync_job_ids,
    process_sync_job,
    request_sync,
    run_due_syncs,
    schedule_due_syncs,
)
from app.services.meta_graph import MetaGraphClient, MetaGraphError
from app.worker import run_once
from publishing_helpers import CSRF, FakeMeta, add_member, connect_account, create_approved_content, create_workspace, meta_error, register

UTC = timezone.utc
FB_SCOPES = ["pages_show_list", "pages_read_engagement", "instagram_basic", "pages_manage_posts", "read_insights"]
IG_SCOPES = ["pages_show_list", "pages_read_engagement", "instagram_basic", "instagram_content_publish", "instagram_manage_insights"]
PAGE_DAILY = {
    "page_media_view": 120,
    "page_total_media_view_unique": 80,
    "page_post_engagements": 15,
    "page_daily_follows_unique": 3,
    "page_daily_unfollows_unique": 1,
    "page_views_total": 9,
    "page_video_views": 40,
}
IG_DAILY = {
    "views": 300,
    "accounts_engaged": 50,
    "total_interactions": 70,
    "likes": 55,
    "comments": 8,
    "shares": 4,
    "saves": 3,
    "replies": 2,
    "profile_links_taps": 1,
}


def _days(flat_params: dict) -> list[date]:
    since = datetime.fromtimestamp(int(flat_params["since"]), UTC).date()
    until = datetime.fromtimestamp(int(flat_params["until"]), UTC).date()
    days = []
    day = since
    while day <= until:
        days.append(day)
        day += timedelta(days=1)
    return days


def _end_time(day: date) -> str:
    return (datetime(day.year, day.month, day.day, 8, tzinfo=UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S+0000")


def fb_insights(*, unsupported: set[str] = frozenset(), omit: set[str] = frozenset()):
    def handler(request: httpx.Request, _flat: dict):
        params = dict(request.url.params)
        metrics = params["metric"].split(",")
        if any(name in unsupported for name in metrics):
            return meta_error(400, 100, "(#100) The value must be a valid insights metric")
        data = []
        for name in metrics:
            if name in omit:
                continue
            values = []
            for day in _days(params):
                value = {"like": 3, "love": 1} if name == "page_actions_post_reactions_total" else PAGE_DAILY[name]
                values.append({"value": value, "end_time": _end_time(day)})
            data.append({"name": name, "period": "day", "values": values})
        return {"data": data, "paging": {}}

    return handler


def fb_post_insights(*, video: bool = False):
    def handler(request: httpx.Request, _flat: dict):
        metrics = dict(request.url.params)["metric"].split(",")
        values = {
            "post_media_view": 500,
            "post_total_media_view_unique": 400,
            "post_clicks": 20,
            "post_reactions_by_type_total": {"like": 30, "love": 5},
            "post_video_views": 250 if video else None,
        }
        return {"data": [{"name": name, "period": "lifetime", "values": [{"value": values[name]}]} for name in metrics if values.get(name) is not None]}

    return handler


def fb_post(post_id: str, *, video: bool = False, target_id: str | None = None, days_ago: int = 3) -> dict:
    created = (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    post = {
        "id": post_id,
        "created_time": created,
        "permalink_url": f"https://www.facebook.com/{post_id}",
        "status_type": "added_video" if video else "added_photos",
        "full_picture": "https://scontent.example/pic.jpg",
        "message": "We launched. #launch",
        "shares": {"count": 7},
        "comments": {"data": [], "summary": {"total_count": 12}},
        "reactions": {"data": [], "summary": {"total_count": 35}},
        "likes": {"data": [], "summary": {"total_count": 30}},
    }
    if target_id:
        post["attachments"] = {"data": [{"media_type": "video" if video else "photo", "type": "video_inline" if video else "photo", "target": {"id": target_id}}]}
    return post


def fb_posts_pages(posts: list[dict], per_page: int = 2):
    def handler(request: httpx.Request, _flat: dict):
        after = dict(request.url.params).get("after")
        start = int(after) if after else 0
        chunk = posts[start : start + per_page]
        body: dict = {"data": chunk, "paging": {}}
        if start + per_page < len(posts):
            body["paging"] = {"cursors": {"after": str(start + per_page)}, "next": "https://graph.facebook.com/next"}
        return body

    return handler


def ig_insights(request: httpx.Request, _flat: dict):
    params = dict(request.url.params)
    metrics = params["metric"].split(",")
    if params.get("metric_type") == "time_series":
        values = [{"value": 100, "end_time": _end_time(day)} for day in _days(params)]
        return {"data": [{"name": "reach", "period": "day", "values": values}]}
    return {"data": [{"name": name, "period": "day", "total_value": {"value": IG_DAILY[name]}} for name in metrics if name in IG_DAILY]}


def ig_media(media_id: str, *, product: str = "FEED", media_type: str = "IMAGE", days_ago: int = 2) -> dict:
    return {
        "id": media_id,
        "caption": "Reel time",
        "media_type": media_type,
        "media_product_type": product,
        "permalink": f"https://www.instagram.com/p/{media_id}/",
        "thumbnail_url": "https://scontent.example/thumb.jpg" if media_type == "VIDEO" else None,
        "media_url": "https://scontent.example/media.jpg",
        "timestamp": (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S+0000"),
        "like_count": 40,
        "comments_count": 6,
    }


def ig_media_insights(request: httpx.Request, _flat: dict):
    metrics = dict(request.url.params)["metric"].split(",")
    values = {"reach": 900, "views": 1500, "likes": 40, "comments": 6, "saved": 11, "shares": 9, "total_interactions": 66, "follows": 2, "profile_visits": 5, "ig_reels_avg_watch_time": 5400, "ig_reels_video_view_total_time": 810000}
    return {"data": [{"name": name, "period": "lifetime", "values": [{"value": values[name]}]} for name in metrics if name in values]}


def fake_facebook(**insight_opts) -> FakeMeta:
    posts = [fb_post("page-1_post1"), fb_post("page-1_post2", days_ago=10), fb_post("page-1_post3", video=True, target_id="video-9", days_ago=20)]
    return FakeMeta(
        responses={
            ("GET", "/page-1"): {"id": "page-1", "name": "Autowok Page", "followers_count": 1200, "fan_count": 1150},
            ("GET", "/page-1/insights"): fb_insights(**insight_opts),
            ("GET", "/page-1/published_posts"): fb_posts_pages(posts),
            ("GET", "/page-1_post1/insights"): fb_post_insights(),
            ("GET", "/page-1_post2/insights"): fb_post_insights(),
            ("GET", "/page-1_post3/insights"): fb_post_insights(video=True),
        }
    )


def fake_instagram() -> FakeMeta:
    return FakeMeta(
        responses={
            ("GET", "/ig-1"): {"id": "ig-1", "username": "autowok", "followers_count": 800, "media_count": 12},
            ("GET", "/ig-1/insights"): ig_insights,
            ("GET", "/ig-1/media"): {"data": [ig_media("ig-media-1"), ig_media("ig-media-2", product="REELS", media_type="VIDEO", days_ago=5)], "paging": {}},
            ("GET", "/ig-media-1/insights"): ig_media_insights,
            ("GET", "/ig-media-2/insights"): ig_media_insights,
        }
    )


def graph_factory(fake: FakeMeta):
    return lambda: MetaGraphClient(transport=httpx.MockTransport(fake.handler))


def setup(client, db_factory, email: str = "owner@example.com", *, instagram: bool = True) -> dict:
    register(client, email)
    workspace_id = create_workspace(client, "Analytics workspace")
    brand = client.post(f"/api/v1/workspaces/{workspace_id}/brands", json={"name": "Brand"}, headers=CSRF).json()
    fb = connect_account(db_factory, workspace_id, scopes=FB_SCOPES)
    ig = connect_account(db_factory, workspace_id, platform="instagram", scopes=IG_SCOPES) if instagram else None
    content = create_approved_content(client, workspace_id, platforms=("facebook",))
    with db_factory() as db:
        for account_id in (fb, ig):
            if account_id:
                db.get(SocialAccount, UUID(account_id)).brand_id = UUID(brand["id"])
        db.add(
            ContentPublication(
                workspace_id=UUID(workspace_id),
                project_id=UUID(content["project_id"]),
                draft_id=UUID(content["drafts"]["facebook"]),
                social_account_id=UUID(fb),
                platform="facebook",
                status="published",
                source="manual",
                idempotency_key="pub-1",
                external_post_id="video-9",
                permalink="https://www.facebook.com/video-9",
                published_at=datetime.now(UTC) - timedelta(days=20),
                caption="We launched.",
            )
        )
        db.commit()
    return {"workspace_id": workspace_id, "brand_id": brand["id"], "fb": fb, "ig": ig, "project_id": content["project_id"]}


def run_sync(db_factory, account_id: str, fake: FakeMeta, *, trigger_user: UUID | None = None) -> AnalyticsSyncJob:
    with db_factory() as db:
        account = db.get(SocialAccount, UUID(account_id))
        user_id = trigger_user or account.connected_by
        job = request_sync(db, account=account, requested_by=user_id, enqueue=False)
        job_id = job.id
    with db_factory() as db:
        process_sync_job(db, job_id, worker_id="test", graph_factory=graph_factory(fake))
    with db_factory() as db:
        return db.get(AnalyticsSyncJob, job_id)


def snapshots(db_factory, account_id: str, key: str | None = None) -> list[AnalyticsSnapshot]:
    with db_factory() as db:
        query = db.query(AnalyticsSnapshot).filter(AnalyticsSnapshot.social_account_id == UUID(account_id))
        if key:
            query = query.filter(AnalyticsSnapshot.metric_key == key)
        return query.order_by(AnalyticsSnapshot.snapshot_date).all()


# Metric catalogue ------------------------------------------------------------------


def test_catalogue_contains_only_current_metrics():
    names = {metric.source_name for metric in M.ACCOUNT_METRICS + M.POST_METRICS}
    for deprecated in ("impressions", "page_impressions", "page_impressions_unique", "post_impressions", "post_impressions_unique", "page_fans", "page_engaged_users", "plays"):
        assert deprecated not in names
    assert M.is_comparable(M.ACCOUNT, "reach") and M.is_comparable(M.POST, "likes")
    assert not M.is_comparable(M.ACCOUNT, "engagements") and not M.is_comparable(M.POST, "engagements")
    assert M.definition("instagram", M.POST, "clicks") is None and "clicks" in M.NOT_SUPPORTED["instagram"]
    assert facebook_format({"status_type": "added_video"}) == "video"
    assert facebook_format({"attachments": {"data": [{"type": "album"}]}}) == "multi_photo"
    assert facebook_format({"status_type": "mobile_status_update"}) == "text"
    assert instagram_format({"media_product_type": "REELS", "media_type": "VIDEO"}) == "reel"
    assert instagram_format({"media_product_type": "FEED", "media_type": "CAROUSEL_ALBUM"}) == "carousel"


# Calculations ------------------------------------------------------------------------


def test_calculations_are_guarded():
    assert C.engagement_rate(50, 1000) == 5.0
    assert C.engagement_rate(50, 0) is None
    assert C.engagement_rate(50, None) is None
    assert C.engagement_rate(None, 100) is None
    assert C.percentage_change(120, 100) == 20.0
    assert C.percentage_change(80, 100) == -20.0
    assert C.percentage_change(120, 0) is None
    assert C.percentage_change(120, None) is None
    assert C.percentage_change(None, 100) is None
    assert C.sum_available([1, None, 2]) == (3.0, 2, 3)
    assert C.sum_available([None, None]) == (None, 0, 2)
    assert C.follower_change([(date(2026, 1, 1), 100), (date(2026, 1, 5), 130)]) == 30
    assert C.follower_change([(date(2026, 1, 1), 100)]) is None
    ranked = C.rank([{"id": "a", "e": 5}, {"id": "b", "e": None}, {"id": "c", "e": 9}], "e")
    assert [item["id"] for item in ranked] == ["c", "a"]
    report = C.consistency([date(2026, 1, 1), date(2026, 1, 8)], date(2026, 1, 1), date(2026, 1, 14))
    assert report["posts"] == 2 and report["posts_per_week"] == 1.0 and report["longest_gap_days"] == 7


def test_error_classification():
    assert E.classify_collection_error(MetaGraphError(400, 10, meta_message="(#10) Not enough viewers for the media to show insights")).category == E.INSUFFICIENT_DATA
    assert E.classify_collection_error(MetaGraphError(400, 10, meta_message="(#10) Permission denied")).category == E.PERMISSION
    assert E.classify_collection_error(MetaGraphError(400, 100, meta_message="(#100) The value must be a valid insights metric")).category == E.UNSUPPORTED_METRIC
    assert E.classify_collection_error(MetaGraphError(400, 100, subcode=33)).category == E.OBJECT_UNAVAILABLE
    rate = E.classify_collection_error(MetaGraphError(400, 80001, retry_after_seconds=600))
    assert rate.category == E.RATE_LIMITED and rate.retry_after_seconds == 600 and rate.retryable and rate.aborts_sync
    assert E.classify_collection_error(MetaGraphError(401, 190)).category == E.TOKEN_EXPIRED
    assert E.classify_collection_error(MetaGraphError(504, is_transient=True)).retryable


# Collection and storage ---------------------------------------------------------------


def test_facebook_sync_collects_snapshots_posts_and_links_publications(client, db_factory, token_key):
    ctx = setup(client, db_factory)
    fake = fake_facebook()
    job = run_sync(db_factory, ctx["fb"], fake)
    assert job.status == "succeeded", job.last_error
    assert job.records_processed > 0 and job.details["posts_processed"] == 3
    assert job.active_guard is None and job.completed_at is not None

    rows = snapshots(db_factory, ctx["fb"])
    keys = {row.metric_key for row in rows}
    assert {"followers", "views", "reach", "engagements", "follows", "unfollows", "page_views", "video_views", "reactions"} <= keys
    views = snapshots(db_factory, ctx["fb"], "views")
    assert len(views) == 31 and all(row.metric_value == 120 for row in views)  # 30-day initial lookback including today
    reactions = snapshots(db_factory, ctx["fb"], "reactions")[0]
    assert reactions.metric_value == 4 and reactions.value_breakdown == {"like": 3, "love": 1}
    assert reactions.source_metric == "page_actions_post_reactions_total" and reactions.api_version
    followers = snapshots(db_factory, ctx["fb"], "followers")
    assert len(followers) == 1 and followers[0].metric_value == 1200
    assert all(row.workspace_id == UUID(ctx["workspace_id"]) and row.brand_id == UUID(ctx["brand_id"]) for row in rows)

    # Pagination: two pages of published posts were fetched.
    assert len(fake.calls_to("GET", "/page-1/published_posts")) == 2
    # Tokens travel only in the Authorization header, never in query strings.
    assert all("page-access-secret" not in json.dumps(call["params"]) for call in fake.calls)

    with db_factory() as db:
        posts = {post.external_post_id: post for post in db.query(PostAnalytics).all()}
        history = {post.external_post_id: [dict(entry.metrics) for entry in post.history] for post in posts.values()}
    assert set(posts) == {"page-1_post1", "page-1_post2", "page-1_post3"}
    post = posts["page-1_post1"]
    assert (post.views, post.reach, post.clicks, post.reactions, post.likes, post.comments, post.shares) == (500, 400, 20, 35, 30, 12, 7)
    assert post.engagements == 35 + 12 + 7 + 20 and post.metric_availability["engagements"] == "calculated"
    assert post.saves is None and post.metric_availability["saves"] == "not_supported_on_platform"
    assert post.video_views is None and post.metric_availability["video_views"] == "not_applicable"
    assert post.content_format == "photo" and post.publication_id is None
    video = posts["page-1_post3"]
    assert video.video_views == 250 and video.content_format == "video"
    # Linked to the Autowok publication through the attachment target id.
    assert video.publication_id is not None and video.project_id == UUID(ctx["project_id"])
    assert len(history["page-1_post3"]) == 1 and history["page-1_post3"][0]["views"] == 500


def test_instagram_sync_collects_account_and_media_metrics(client, db_factory, token_key):
    ctx = setup(client, db_factory)
    job = run_sync(db_factory, ctx["ig"], fake_instagram())
    assert job.status == "succeeded", job.last_error
    reach = snapshots(db_factory, ctx["ig"], "reach")
    assert len(reach) == 31 and reach[0].metric_value == 100 and reach[0].source_metric == "reach"
    assert snapshots(db_factory, ctx["ig"], "views")[0].metric_value == 300
    assert snapshots(db_factory, ctx["ig"], "engagements")[0].source_metric == "total_interactions"
    assert snapshots(db_factory, ctx["ig"], "followers")[0].metric_value == 800
    assert not snapshots(db_factory, ctx["ig"], "impressions")
    with db_factory() as db:
        posts = {post.external_post_id: post for post in db.query(PostAnalytics).all()}
    image = posts["ig-media-1"]
    assert (image.reach, image.views, image.likes, image.comments, image.saves, image.shares, image.engagements) == (900, 1500, 40, 6, 11, 9, 66)
    assert image.clicks is None and image.metric_availability["clicks"] == "not_supported_on_platform"
    assert image.content_format == "image" and image.raw_metrics["normalized_extras"]["follows"] == 2
    reel = posts["ig-media-2"]
    assert reel.content_format == "reel" and reel.raw_metrics["normalized_extras"]["reel_avg_watch_time"] == 5400
    assert "follows" not in reel.raw_metrics.get("normalized_extras", {})


def test_duplicate_snapshots_are_prevented_on_resync(client, db_factory, token_key):
    ctx = setup(client, db_factory)
    first = run_sync(db_factory, ctx["fb"], fake_facebook())
    count_before = len(snapshots(db_factory, ctx["fb"]))
    with db_factory() as db:
        db.get(AnalyticsSyncJob, first.id).completed_at = datetime.now(UTC) - timedelta(hours=2)
        db.commit()
    second = run_sync(db_factory, ctx["fb"], fake_facebook())
    assert second.status == "succeeded"
    assert second.details["snapshots_created"] <= 1  # a new day may have started during the test
    assert len(snapshots(db_factory, ctx["fb"])) <= count_before + 1
    with db_factory() as db:
        assert db.query(PostAnalytics).count() == 3
        post = db.query(PostAnalytics).filter(PostAnalytics.external_post_id == "page-1_post1").one()
        assert len(post.history) == 1, "same collection day must update the history row"


def test_unsupported_and_missing_metrics_are_marked_unavailable(client, db_factory, token_key):
    ctx = setup(client, db_factory)
    fake = fake_facebook(unsupported={"page_video_views"}, omit={"page_views_total"})
    job = run_sync(db_factory, ctx["fb"], fake)
    assert job.status == "succeeded"
    assert job.details["unavailable"]["video_views"] == "unsupported_metric"
    assert job.details["unavailable"]["page_views"] == "not_returned"
    assert not snapshots(db_factory, ctx["fb"], "video_views") and not snapshots(db_factory, ctx["fb"], "page_views")
    assert len(snapshots(db_factory, ctx["fb"], "views")) == 31  # fallback requested the other metrics one by one
    singles = [call for call in fake.calls_to("GET", "/page-1/insights") if "," not in call["params"]["metric"]]
    assert len(singles) >= 8


def test_missing_insights_permission_marks_metrics_unavailable_without_failing(client, db_factory, token_key):
    ctx = setup(client, db_factory)
    with db_factory() as db:
        db.get(SocialAccount, UUID(ctx["fb"])).granted_scopes = ["pages_show_list", "pages_read_engagement", "pages_manage_posts"]
        db.commit()
    fake = fake_facebook()
    job = run_sync(db_factory, ctx["fb"], fake)
    assert job.status == "partial"
    assert job.details["unavailable"]["views"] == "missing_permission:read_insights"
    assert not fake.calls_to("GET", "/page-1/insights") and not fake.calls_to("GET", "/page-1_post1/insights")
    assert snapshots(db_factory, ctx["fb"], "followers")[0].metric_value == 1200
    with db_factory() as db:
        post = db.query(PostAnalytics).filter(PostAnalytics.external_post_id == "page-1_post1").one()
    assert post.views is None and post.metric_availability["views"] == "missing_permission:read_insights"
    assert post.comments == 12 and post.reactions == 35 and post.likes == 30


def test_instagram_insufficient_data_keeps_field_counts(client, db_factory, token_key):
    ctx = setup(client, db_factory)
    fake = fake_instagram()
    fake.responses[("GET", "/ig-media-1/insights")] = meta_error(400, 10, "(#10) Not enough viewers for the media to show insights")
    job = run_sync(db_factory, ctx["ig"], fake)
    assert job.status == "succeeded"
    with db_factory() as db:
        post = db.query(PostAnalytics).filter(PostAnalytics.external_post_id == "ig-media-1").one()
    assert post.likes == 40 and post.comments == 6
    assert post.reach is None and post.metric_availability["reach"] == "insufficient_data"
    assert post.engagements is None


def test_rate_limit_reschedules_with_meta_hint(client, db_factory, token_key):
    ctx = setup(client, db_factory)
    fake = fake_facebook()
    usage = json.dumps({"123": [{"type": "pages", "call_count": 100, "total_cputime": 10, "total_time": 10, "estimated_time_to_regain_access": 7}]})
    fake.responses[("GET", "/page-1/insights")] = httpx.Response(400, json={"error": {"code": 80001, "message": "limit"}}, headers={"X-Business-Use-Case-Usage": usage})
    job = run_sync(db_factory, ctx["fb"], fake)
    assert job.status == "pending" and job.error_category == "rate_limited"
    delay = (job.next_attempt_at.replace(tzinfo=UTC) - datetime.now(UTC)).total_seconds()
    assert 300 < delay <= 7 * 60 + 5 and job.details["retry_in_seconds"] == 420
    assert job.active_guard is not None  # still the active job for the account
    with db_factory() as db:
        assert due_sync_job_ids(db) == []  # not due yet
        assert due_sync_job_ids(db, now=datetime.now(UTC) + timedelta(minutes=8)) == [job.id]
    with db_factory() as db:
        with pytest.raises(SyncConflict):
            request_sync(db, account=db.get(SocialAccount, UUID(ctx["fb"])), requested_by=uuid4(), enqueue=False)


def test_expired_token_and_permission_failures_stop_the_job(client, db_factory, token_key):
    ctx = setup(client, db_factory)
    fake = fake_facebook()
    fake.responses[("GET", "/page-1")] = meta_error(400, 190, "Error validating access token")
    job = run_sync(db_factory, ctx["fb"], fake)
    assert job.status == "failed" and job.error_category == "token_expired" and job.active_guard is None
    with db_factory() as db:
        account = db.get(SocialAccount, UUID(ctx["fb"]))
        assert account.connection_status == "expired" and account.last_error_code == "token_expired"
        assert db.query(AnalyticsSnapshot).count() == 0

    ig_fake = fake_instagram()
    ig_fake.responses[("GET", "/ig-1/insights")] = meta_error(403, 200, "(#200) Requires instagram_manage_insights")
    job = run_sync(db_factory, ctx["ig"], ig_fake)
    assert job.status == "failed" and job.error_category == "permission" and "Reconnect" in job.last_error
    with db_factory() as db:
        assert db.get(SocialAccount, UUID(ctx["ig"])).last_error_code == "insights_permission_denied"


def test_network_timeout_retries_then_fails(client, db_factory, token_key, monkeypatch):
    ctx = setup(client, db_factory)
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "analytics_sync_max_attempts", 2)
    fake = fake_facebook()
    fake.responses[("GET", "/page-1")] = httpx.ReadTimeout("slow")
    job = run_sync(db_factory, ctx["fb"], fake)
    assert job.status == "pending" and job.error_category == "network" and job.attempt_count == 1
    with db_factory() as db:
        process_sync_job(db, job.id, worker_id="test", graph_factory=graph_factory(fake), now=datetime.now(UTC) + timedelta(hours=1))
        job = db.get(AnalyticsSyncJob, job.id)
        assert job.status == "failed" and job.attempt_count == 2 and job.active_guard is None


def test_scheduler_creates_jobs_and_worker_processes_them(client, db_factory, token_key, monkeypatch):
    ctx = setup(client, db_factory)
    fake_fb, fake_ig = fake_facebook(), fake_instagram()
    combined = FakeMeta(responses={**fake_fb.responses, **fake_ig.responses})
    from app.services.analytics import sync as sync_module

    monkeypatch.setattr(sync_module, "MetaGraphClient", graph_factory(combined))
    with db_factory() as db:
        assert schedule_due_syncs(db) == 2
        assert schedule_due_syncs(db) == 0  # one active job per account
        assert run_due_syncs(db, worker_id="w1") == 2
        assert run_due_syncs(db, worker_id="w1") == 0
        assert schedule_due_syncs(db) == 0  # within the sync interval
        assert schedule_due_syncs(db, now=datetime.now(UTC) + timedelta(hours=13)) == 2
        statuses = {job.status for job in db.query(AnalyticsSyncJob).all()}
        assert statuses == {"succeeded", "pending"}
    from app.services.analytics import worker_tasks

    tasks: list = []
    worker_tasks.register(tasks)
    worker_tasks.register(tasks)
    assert len(tasks) == 2
    assert run_once(db_factory, worker_id="loop", tasks=tasks) >= 2


# API ------------------------------------------------------------------------------------


def _synced_context(client, db_factory):
    ctx = setup(client, db_factory)
    assert run_sync(db_factory, ctx["fb"], fake_facebook()).status == "succeeded"
    assert run_sync(db_factory, ctx["ig"], fake_instagram()).status == "succeeded"
    return ctx


def test_overview_filters_and_platform_separation(client, db_factory, token_key):
    ctx = _synced_context(client, db_factory)
    base = f"/api/v1/workspaces/{ctx['workspace_id']}/analytics"
    overview = client.get(f"{base}/overview").json()
    assert {account["social_account_id"] for account in overview["accounts"]} == {ctx["fb"], ctx["ig"]}
    metrics = {metric["key"]: metric for metric in overview["metrics"]}
    followers = metrics["followers"]
    assert followers["comparable"] and followers["combined_value"] == 2000
    reach = metrics["reach"]
    by_platform = {entry["platform"]: entry for entry in reach["platforms"]}
    assert by_platform["facebook_page"]["value"] == 80 * 28 and by_platform["facebook_page"]["source_metric"] == "page_total_media_view_unique"
    assert by_platform["instagram"]["value"] == 100 * 28 and by_platform["instagram"]["source_metric"] == "reach"
    assert by_platform["facebook_page"]["previous_value"] == 80 * 3  # only three earlier days exist in the 30-day lookback
    engagements = metrics["engagements"]
    assert engagements["comparable"] is False and engagements["combined_value"] is None
    assert "differ" in engagements["label"]
    assert overview["published_posts"]["total"] == 5 and overview["published_posts"]["from_autowok"] == 1
    assert overview["top_posts"][0]["metrics"]["engagements"] is not None
    assert overview["freshness"]["newest_collected_at"]

    fb_only = client.get(f"{base}/overview", params={"platform": "facebook_page"}).json()
    assert [a["platform"] for a in fb_only["accounts"]] == ["facebook_page"]
    assert all(len(metric["platforms"]) == 1 for metric in fb_only["metrics"])
    by_account = client.get(f"{base}/overview", params={"social_account_id": ctx["ig"]}).json()
    assert [a["social_account_id"] for a in by_account["accounts"]] == [ctx["ig"]]
    by_brand = client.get(f"{base}/overview", params={"brand_id": ctx["brand_id"]}).json()
    assert len(by_brand["accounts"]) == 2
    other_brand = client.post(f"/api/v1/workspaces/{ctx['workspace_id']}/brands", json={"name": "Other"}, headers=CSRF).json()
    empty = client.get(f"{base}/overview", params={"brand_id": other_brand["id"]}).json()
    assert empty["accounts"] == [] and empty["published_posts"]["total"] == 0 and empty["top_posts"] == []
    assert all(entry["value"] is None for metric in empty["metrics"] for entry in metric["platforms"])

    today = datetime.now(UTC).date()
    ranged = client.get(f"{base}/overview", params={"start": (today - timedelta(days=6)).isoformat(), "end": today.isoformat(), "platform": "instagram"}).json()
    assert ranged["filters"]["days"] == 7
    assert {m["key"]: m for m in ranged["metrics"]}["views"]["platforms"][0]["value"] == 300 * 7
    assert client.get(f"{base}/overview", params={"start": today.isoformat(), "end": (today - timedelta(days=1)).isoformat()}).status_code == 422
    assert client.get(f"{base}/overview", params={"brand_id": str(uuid4())}).status_code == 404
    assert client.get(f"{base}/overview", params={"platform": "tiktok"}).status_code == 422


def test_timeseries_accounts_posts_and_comparisons(client, db_factory, token_key):
    ctx = _synced_context(client, db_factory)
    base = f"/api/v1/workspaces/{ctx['workspace_id']}/analytics"
    series = client.get(f"{base}/timeseries", params={"metric": "reach"}).json()
    assert {s["platform"] for s in series["series"]} == {"facebook_page", "instagram"}
    fb_series = next(s for s in series["series"] if s["platform"] == "instagram")
    assert len(fb_series["points"]) == 28 and fb_series["points"][-1]["value"] == 100 and fb_series["supported"]
    saves = client.get(f"{base}/timeseries", params={"metric": "saves", "group_by": "account"}).json()
    fb_saves = next(s for s in saves["series"] if s["platform"] == "facebook_page")
    assert fb_saves["supported"] is False and all(p["value"] is None for p in fb_saves["points"])
    assert client.get(f"{base}/timeseries", params={"metric": "impressions"}).status_code == 422

    accounts = client.get(f"{base}/accounts").json()
    ig = next(a for a in accounts if a["account"]["platform"] == "instagram")
    metric_keys = [m["key"] for m in ig["metrics"]]
    assert "reach" in metric_keys and "clicks" not in metric_keys
    assert ig["sync"]["last_synced_at"] and ig["sync"]["insights_available"]
    assert ig["follower_change"] is None  # single follower snapshot so far
    single = client.get(f"{base}/accounts/{ctx['fb']}").json()
    assert single["account"]["id"] == ctx["fb"]
    assert client.get(f"{base}/accounts/{uuid4()}").status_code == 404

    posts = client.get(f"{base}/posts", params={"sort": "engagements", "order": "desc"}).json()
    assert posts["total"] == 5 and posts["items"][0]["metrics"]["engagements"] >= posts["items"][-1]["metrics"]["engagements"]
    reels = client.get(f"{base}/posts", params={"platform": "instagram", "content_format": "reel"}).json()
    assert reels["total"] == 1 and reels["items"][0]["content_format_label"] == "Reel"
    autowok_posts = client.get(f"{base}/posts", params={"source": "autowok"}).json()
    assert autowok_posts["total"] == 1 and autowok_posts["items"][0]["project_id"] == ctx["project_id"]
    assert autowok_posts["items"][0]["project_title"] == "Launch post"
    ranged = client.get(f"{base}/posts", params={"min_engagements": 70, "max_engagements": 80}).json()
    assert ranged["total"] == 3 and all(item["metrics"]["engagements"] == 74 for item in ranged["items"])  # the three Facebook posts
    assert client.get(f"{base}/posts", params={"min_engagements": 60, "max_engagements": 69}).json()["total"] == 2  # the two Instagram posts
    detail = client.get(f"{base}/posts/{posts['items'][0]['id']}").json()
    assert detail["history"] and detail["definitions"] and detail["engagement_rate"] is not None
    assert client.get(f"{base}/posts/{uuid4()}").status_code == 404

    fb_post = next(p for p in posts["items"] if p["platform"] == "facebook_page")
    ig_post = next(p for p in posts["items"] if p["platform"] == "instagram")
    compared = client.post(f"{base}/posts/compare", json={"post_ids": [fb_post["id"], ig_post["id"]]}, headers=CSRF).json()
    assert compared["mixed_platforms"] is True
    by_key = {m["key"]: m for m in compared["metrics"]}
    assert by_key["likes"]["comparable"] is True and by_key["engagements"]["comparable"] is False
    assert by_key["saves"]["values"][0]["availability"] == "not_supported_on_platform"
    assert client.post(f"{base}/posts/compare", json={"post_ids": [fb_post["id"], str(uuid4())]}, headers=CSRF).status_code == 404

    comparison = client.get(f"{base}/platforms/compare").json()
    assert comparison["meaningful"] is True
    post_metrics = {m["key"]: m for m in comparison["post_metrics"]}
    assert post_metrics["reach"]["comparable"] and not post_metrics["engagements"]["comparable"]
    ig_saves = next(e for e in post_metrics["saves"]["platforms"] if e["platform"] == "facebook_page")
    assert ig_saves["availability"] == "not_supported" and ig_saves["total"] is None
    assert {r["platform"] for r in comparison["engagement_rates"]} == {"facebook_page", "instagram"}

    performance = client.get(f"{base}/content-performance").json()
    assert performance["post_count"] == 5 and performance["ranking_metric"] == "engagement_rate"
    assert performance["top_posts"][0]["engagement_rate"] >= performance["top_posts"][-1]["engagement_rate"]
    assert performance["formats"] and performance["weekly_trend"] and performance["consistency"]["posts"] == 5
    assert "predict" in performance["best_format_note"] or "Not enough" in performance["best_format_note"]
    summary = client.post(f"{base}/content-performance/summary", headers=CSRF).json()
    assert summary["available"] is False and "AI interpretation" in summary["label"]  # Groq not configured


def test_reports_and_exports(client, db_factory, token_key):
    ctx = _synced_context(client, db_factory)
    base = f"/api/v1/workspaces/{ctx['workspace_id']}/analytics"
    report = client.get(f"{base}/reports", params={"brand_id": ctx["brand_id"]}).json()
    assert report["brand"]["name"] == "Brand" and len(report["accounts"]) == 2 and len(report["posts"]) == 5
    assert report["definitions"] and report["collection"]["newest_collected_at"]
    assert any("saves" in item.lower() or "Facebook" in item for item in report["missing_data"])

    csv_response = client.get(f"{base}/reports/export", params={"format": "csv"})
    assert csv_response.status_code == 200 and csv_response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in csv_response.headers["content-disposition"]
    text = csv_response.text
    assert "Autowok analytics report" in text and "page_total_media_view_unique" in text and "Metric definitions" in text
    assert "Post performance" in text and "https://www.instagram.com/p/ig-media-1/" in text
    assert "page-access-secret" not in text

    pdf_response = client.get(f"{base}/reports/export", params={"format": "pdf", "platform": "instagram"})
    assert pdf_response.status_code == 200 and pdf_response.headers["content-type"] == "application/pdf"
    assert pdf_response.content.startswith(b"%PDF-1.4") and b"%%EOF" in pdf_response.content
    assert b"/Type /Pages" in pdf_response.content and b"Metric definitions" in pdf_response.content
    assert client.get(f"{base}/reports/export", params={"format": "xlsx"}).status_code == 422


def test_sync_endpoints_roles_rate_limits_and_history(client, db_factory, token_key, client_factory):
    ctx = setup(client, db_factory)
    base = f"/api/v1/workspaces/{ctx['workspace_id']}/analytics"
    status = client.get(f"{base}/sync/status").json()
    assert status["active_jobs"] == 0 and len(status["accounts"]) == 2
    assert all(a["last_synced_at"] is None and a["insights_available"] for a in status["accounts"])

    accepted = client.post(f"{base}/sync", json={}, headers=CSRF)
    assert accepted.status_code == 202 and len(accepted.json()["jobs"]) == 2
    again = client.post(f"{base}/sync", json={}, headers=CSRF)
    assert again.status_code == 202 and again.json()["jobs"] == [] and len(again.json()["skipped"]) == 2
    assert client.post(f"{base}/sync", json={"social_account_id": ctx["fb"]}, headers=CSRF).status_code == 409
    assert client.post(f"{base}/sync", json={"social_account_id": str(uuid4())}, headers=CSRF).status_code == 404
    assert client.get(f"{base}/sync/status").json()["active_jobs"] == 2

    fake = FakeMeta(responses={**fake_facebook().responses, **fake_instagram().responses})
    with db_factory() as db:
        assert run_due_syncs(db, worker_id="api-test", graph_factory=graph_factory(fake)) == 2
    status = client.get(f"{base}/sync/status").json()
    assert all(a["last_sync_status"] == "succeeded" and a["last_synced_at"] for a in status["accounts"])
    history = client.get(f"{base}/sync/history", params={"social_account_id": ctx["fb"]}).json()
    assert len(history) == 1 and history[0]["trigger"] == "manual" and history[0]["records_processed"] > 0
    assert history[0]["account_name"] == "Autowok Page" and "unavailable" in history[0]["details"]
    # Cooldown: a completed sync blocks another manual refresh for a while.
    assert client.post(f"{base}/sync", json={"social_account_id": ctx["fb"]}, headers=CSRF).status_code == 429

    # Members can read but not refresh.
    register_member = client_factory()
    with register_member as member:
        register(member, "member@example.com")
    add_member(client, ctx["workspace_id"], "member@example.com")
    with client_factory() as member:
        member.post("/api/v1/auth/login", json={"email": "member@example.com", "password": "StrongPassword#1234"}, headers=CSRF)
        assert member.get(f"{base}/overview").status_code == 200
        assert member.get(f"{base}/reports/export", params={"format": "csv"}).status_code == 200
        assert member.post(f"{base}/sync", json={}, headers=CSRF).status_code == 403


def test_workspace_isolation(client, db_factory, token_key, client_factory):
    ctx = _synced_context(client, db_factory)
    base = f"/api/v1/workspaces/{ctx['workspace_id']}/analytics"
    post_id = client.get(f"{base}/posts").json()["items"][0]["id"]
    with client_factory() as other:
        register(other, "intruder@example.com")
        other_workspace = create_workspace(other, "Other")
        other_base = f"/api/v1/workspaces/{other_workspace}/analytics"
        assert other.get(f"{base}/overview").status_code == 404
        assert other.get(f"{base}/posts/{post_id}").status_code == 404
        assert other.get(f"{base}/reports/export", params={"format": "csv"}).status_code == 404
        assert other.post(f"{base}/sync", json={}, headers=CSRF).status_code == 404
        assert other.get(f"{other_base}/posts/{post_id}").status_code == 404
        assert other.post(f"{other_base}/posts/compare", json={"post_ids": [post_id, str(uuid4())]}, headers=CSRF).status_code == 404
        assert other.get(f"{other_base}/overview", params={"social_account_id": ctx["fb"]}).status_code == 404
        assert other.get(f"{other_base}/overview", params={"brand_id": ctx["brand_id"]}).status_code == 404
        mine = other.get(f"{other_base}/overview").json()
        assert mine["accounts"] == [] and mine["published_posts"]["total"] == 0
        assert other.get(f"{other_base}/posts").json()["total"] == 0
        assert other.get(f"{other_base}/sync/history").json() == []
        csv_text = other.get(f"{other_base}/reports/export", params={"format": "csv"}).text
        assert "Autowok Page" not in csv_text and "ig-media-1" not in csv_text
