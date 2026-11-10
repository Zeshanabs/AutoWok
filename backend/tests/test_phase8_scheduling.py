from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
import redis

from app.models import ContentPublication, ScheduledPost, SocialAccount
from app.services import redis_client as redis_module
from app.services.publishing import service as publishing_service
from app.services.publishing.queue import READY_QUEUE_KEY, wait_for_publication
from app.services.scheduling import worker_tasks
from app.services.scheduling.service import schedule_due_posts
from app.services.scheduling.timezones import TimezoneError, calendar_range, local_to_utc, utc_to_local
from app.worker import run_once
from publishing_helpers import (
    CSRF,
    FakeMeta,
    add_member,
    connect_account,
    create_approved_content,
    create_workspace,
    jpeg_bytes,
    meta_error,
    register,
    run_job,
    upload,
)

UTC = timezone.utc
FB_OK = {("POST", "/page-1/photos"): {"id": "photo", "post_id": "page-1_sched"}, ("GET", "/page-1_sched"): {"permalink_url": "https://facebook.com/sched"}}


def future_local(tz: str = "Asia/Karachi", *, days: int = 2, hour: int = 9, minute: int = 30) -> str:
    local = datetime.now(ZoneInfo(tz)) + timedelta(days=days)
    return local.replace(hour=hour, minute=minute, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")


def setup(client, db_factory, email: str):
    register(client, email)
    workspace_id = create_workspace(client)
    brand = client.post(f"/api/v1/workspaces/{workspace_id}/brands", json={"name": "Brand"}, headers=CSRF).json()
    image = upload(client, workspace_id, jpeg_bytes(1080, 1080), "post.jpg").json()
    project = client.post(
        "/api/v1/content/projects",
        json={"workspace_id": workspace_id, "brand_id": brand["id"], "title": "Scheduled launch", "selected_platforms": ["facebook", "instagram"]},
        headers=CSRF,
    ).json()
    drafts = {}
    for platform in ("facebook", "instagram"):
        drafts[platform] = client.post(
            f"/api/v1/content/projects/{project['id']}/drafts",
            json={"platform": platform, "title": "Launch", "body": "Coming soon.", "hashtags": ["#soon"]},
            headers=CSRF,
        ).json()["id"]
        client.put(f"/api/v1/content/drafts/{drafts[platform]}/media", json={"media_asset_ids": [image["id"]]}, headers=CSRF)
    submitted = client.post(f"/api/v1/content/projects/{project['id']}/submit-for-approval", json={}, headers=CSRF).json()
    client.post(f"/api/v1/content/projects/{project['id']}/approvals/{submitted['id']}/decision", json={"status": "approved"}, headers=CSRF)
    fb = connect_account(db_factory, workspace_id)
    ig = connect_account(db_factory, workspace_id, platform="instagram")
    return {"workspace_id": workspace_id, "brand_id": brand["id"], "project_id": project["id"], "drafts": drafts, "fb": fb, "ig": ig, "image": image}


def schedule(client, ctx, *, platform: str = "facebook", local: str | None = None, tz: str = "Asia/Karachi", account: str | None = None, **extra):
    body = {
        "draft_id": ctx["drafts"][platform],
        "social_account_id": account or ctx["fb" if platform == "facebook" else "ig"],
        "scheduled_local": local or future_local(tz),
        "timezone": tz,
        "confirm": True,
        **extra,
    }
    return client.post(f"/api/v1/workspaces/{ctx['workspace_id']}/scheduled-posts", json=body, headers=CSRF)


def post_row(db_factory, schedule_id: str) -> ScheduledPost:
    with db_factory() as db:
        row = db.get(ScheduledPost, UUID(schedule_id))
        db.expunge(row)
        return row


def run_due(db_factory, at: datetime) -> int:
    with db_factory() as db:
        return schedule_due_posts(db, now=at)


def due_time(row: ScheduledPost, seconds: int = 5) -> datetime:
    return row.scheduled_at.replace(tzinfo=UTC) + timedelta(seconds=seconds)


# Timezones and calendar ranges ---------------------------------------------


def test_local_to_utc_conversion_and_dst_edge_cases():
    utc, local = local_to_utc("2026-11-20T09:30", "Asia/Karachi")
    assert utc == datetime(2026, 11, 20, 4, 30, tzinfo=UTC)
    assert local == "2026-11-20T09:30"
    assert utc_to_local(utc, "America/New_York") == "2026-11-19T23:30"

    summer, _ = local_to_utc("2026-07-01T09:00", "America/New_York")
    winter, _ = local_to_utc("2026-12-01T09:00", "America/New_York")
    assert summer.hour == 13 and winter.hour == 14  # EDT vs EST

    with pytest.raises(TimezoneError, match="does not exist"):
        local_to_utc("2026-03-08T02:30", "America/New_York")
    with pytest.raises(TimezoneError, match="happens twice"):
        local_to_utc("2026-11-01T01:30", "America/New_York")
    earlier, _ = local_to_utc("2026-11-01T01:30", "America/New_York", ambiguous="earlier")
    later, _ = local_to_utc("2026-11-01T01:30", "America/New_York", ambiguous="later")
    assert later - earlier == timedelta(hours=1)
    with pytest.raises(TimezoneError):
        local_to_utc("2026-11-20T09:30", "Mars/Olympus")
    with pytest.raises(TimezoneError):
        local_to_utc("20/11/2026 9am", "UTC")


def test_calendar_ranges_for_month_week_day_and_list():
    start, end, days = calendar_range("month", date(2026, 11, 15), "Asia/Karachi")
    assert days[0] == date(2026, 10, 26) and days[-1] == date(2026, 12, 6)  # Monday-start full weeks
    assert len(days) % 7 == 0
    assert start == datetime(2026, 10, 25, 19, 0, tzinfo=UTC)  # 00:00 PKT = 19:00 UTC previous day
    assert end == datetime(2026, 12, 6, 19, 0, tzinfo=UTC)

    _start, _end, week = calendar_range("week", date(2026, 11, 12), "UTC")
    assert week[0] == date(2026, 11, 9) and len(week) == 7 and week[0].weekday() == 0

    day_start, day_end, day = calendar_range("day", date(2026, 3, 8), "America/New_York")
    assert day == [date(2026, 3, 8)]
    assert day_end - day_start == timedelta(hours=23)  # DST spring-forward day is 23 hours

    _s, _e, listing = calendar_range("list", date(2026, 11, 1), "UTC")
    assert len(listing) == 30
    with pytest.raises(TimezoneError):
        calendar_range("year", date(2026, 1, 1), "UTC")


def test_user_timezone_preferences(client):
    register(client, "prefs@example.com")
    default = client.get("/api/v1/me/preferences").json()
    assert default["timezone"] == "UTC" and default["timezone_is_default"] is True
    updated = client.patch("/api/v1/me/preferences", json={"timezone": "Asia/Karachi"}, headers=CSRF)
    assert updated.status_code == 200 and updated.json()["timezone"] == "Asia/Karachi"
    assert client.patch("/api/v1/me/preferences", json={"timezone": "Not/AZone"}, headers=CSRF).status_code == 422
    assert "Asia/Karachi" in client.get("/api/v1/timezones").json()["timezones"]
    workspace_id = create_workspace(client)
    assert client.get(f"/api/v1/workspaces/{workspace_id}/calendar").json()["timezone"] == "Asia/Karachi"


# Scheduling validation ------------------------------------------------------


def test_create_schedule_stores_utc_and_records_history(client, db_factory, token_key):
    ctx = setup(client, db_factory, "sched-create@example.com")
    response = schedule(client, ctx, local="2027-01-15T10:00", tz="Asia/Karachi", brand_id=ctx["brand_id"], project_id=ctx["project_id"])
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["scheduled_at"] == "2027-01-15T05:00:00Z"
    assert data["scheduled_local"] == "2027-01-15T10:00"
    assert data["timezone"] == "Asia/Karachi" and data["utc_offset"] == "UTC+05:00"
    assert data["status"] == "scheduled" and data["brand_name"] == "Brand"
    assert data["approval_status"] == "approved"
    assert [item["action"] for item in data["history"]] == ["created"]
    assert data["can_edit"] and data["can_cancel"]

    duplicate = schedule(client, ctx, local="2027-01-16T10:00")
    assert duplicate.status_code == 400 and "already scheduled" in duplicate.json()["detail"]
    immediate = client.post(
        f"/api/v1/content/drafts/{ctx['drafts']['facebook']}/publish",
        json={"social_account_id": ctx["fb"], "confirm": True},
        headers=CSRF,
    )
    assert immediate.status_code == 400 and "already scheduled" in immediate.json()["detail"]
    assert schedule(client, ctx, platform="instagram").status_code == 201


def test_schedule_validation_rejections(client, client_factory, db_factory, token_key):
    ctx = setup(client, db_factory, "sched-reject@example.com")
    past = (datetime.now(ZoneInfo("UTC")) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    assert "future" in schedule(client, ctx, local=past, tz="UTC").json()["detail"]
    assert schedule(client, ctx, local="2026-03-08T02:30", tz="America/New_York").status_code == 422
    assert schedule(client, ctx, local=future_local(), tz="Nowhere/City").status_code == 422
    assert schedule(client, ctx, confirm=False).status_code == 400
    assert "Facebook Page" in schedule(client, ctx, account=ctx["ig"]).json()["detail"]

    disconnected = connect_account(db_factory, ctx["workspace_id"], platform_account_id="page-off", status="disconnected")
    assert "disconnected" in schedule(client, ctx, account=disconnected).json()["detail"]

    other_brand = client.post(f"/api/v1/workspaces/{ctx['workspace_id']}/brands", json={"name": "Other"}, headers=CSRF).json()
    assert "brand" in schedule(client, ctx, brand_id=other_brand["id"]).json()["detail"]

    unapproved = create_approved_content(client, ctx["workspace_id"], platforms=("facebook",), approve=False)
    response = client.post(
        f"/api/v1/workspaces/{ctx['workspace_id']}/scheduled-posts",
        json={"draft_id": unapproved["drafts"]["facebook"], "social_account_id": ctx["fb"], "scheduled_local": future_local(), "timezone": "Asia/Karachi", "confirm": True},
        headers=CSRF,
    )
    assert response.status_code == 400 and "approved" in response.json()["detail"]

    client.delete(f"/api/v1/media-assets/{ctx['image']['id']}", headers=CSRF)
    archived = schedule(client, ctx)
    assert archived.status_code == 400 and "archived" in archived.json()["detail"]

    with client_factory() as member:
        register(member, "sched-member@example.com")
        add_member(client, ctx["workspace_id"], "sched-member@example.com")
        assert schedule(member, ctx).status_code == 403
        assert member.get(f"/api/v1/workspaces/{ctx['workspace_id']}/calendar").status_code == 200

    with client_factory() as outsider:
        register(outsider, "sched-outsider@example.com")
        own_workspace = create_workspace(outsider, "Outsider")
        foreign = outsider.post(
            f"/api/v1/workspaces/{own_workspace}/scheduled-posts",
            json={"draft_id": ctx["drafts"]["facebook"], "social_account_id": ctx["fb"], "scheduled_local": future_local(), "timezone": "UTC", "confirm": True},
            headers=CSRF,
        )
        assert foreign.status_code == 404
        assert outsider.get(f"/api/v1/workspaces/{ctx['workspace_id']}/calendar").status_code == 404
        assert outsider.get(f"/api/v1/workspaces/{ctx['workspace_id']}/scheduled-posts").status_code == 404
        assert outsider.get(f"/api/v1/workspaces/{ctx['workspace_id']}/publishing/queue").status_code == 404


def test_update_reschedule_cancel_and_history(client, client_factory, db_factory, token_key):
    ctx = setup(client, db_factory, "sched-edit@example.com")
    created = schedule(client, ctx, local="2027-02-01T09:00").json()
    second_page = connect_account(db_factory, ctx["workspace_id"], platform_account_id="page-2")

    rescheduled = client.post(
        f"/api/v1/scheduled-posts/{created['id']}/reschedule",
        json={"scheduled_local": "2027-02-02T18:15", "timezone": "Europe/London"},
        headers=CSRF,
    )
    assert rescheduled.status_code == 200, rescheduled.text
    assert rescheduled.json()["scheduled_at"] == "2027-02-02T18:15:00Z"
    assert rescheduled.json()["revision"] == 2

    updated = client.patch(f"/api/v1/scheduled-posts/{created['id']}", json={"social_account_id": second_page}, headers=CSRF)
    assert updated.status_code == 200 and updated.json()["social_account_id"] == second_page
    assert client.patch(f"/api/v1/scheduled-posts/{created['id']}", json={}, headers=CSRF).status_code == 422

    with client_factory() as member:
        register(member, "sched-edit-member@example.com")
        add_member(client, ctx["workspace_id"], "sched-edit-member@example.com")
        assert member.post(f"/api/v1/scheduled-posts/{created['id']}/cancel", headers=CSRF).status_code == 403
        assert member.get(f"/api/v1/scheduled-posts/{created['id']}").json()["can_cancel"] is False

    cancelled = client.post(f"/api/v1/scheduled-posts/{created['id']}/cancel", headers=CSRF)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert client.post(f"/api/v1/scheduled-posts/{created['id']}/cancel", headers=CSRF).status_code == 409
    assert client.post(f"/api/v1/scheduled-posts/{created['id']}/reschedule", json={"scheduled_local": "2027-03-01T09:00"}, headers=CSRF).status_code == 409

    history = client.get(f"/api/v1/scheduled-posts/{created['id']}/history").json()
    assert [item["action"] for item in history] == ["created", "rescheduled", "updated", "cancelled"]
    assert history[1]["previous_scheduled_at"] == "2027-02-01T04:00:00Z"
    assert history[1]["new_scheduled_at"] == "2027-02-02T18:15:00Z"
    assert history[0]["performed_by_name"]

    # Cancelling released the slot: the same draft can be scheduled again.
    assert schedule(client, ctx).status_code == 201


def test_calendar_views_filters_and_status_display(client, db_factory, token_key):
    ctx = setup(client, db_factory, "calendar@example.com")
    fb_post = schedule(client, ctx, local="2027-03-10T09:00", tz="Asia/Karachi").json()
    ig_post = schedule(client, ctx, platform="instagram", local="2027-03-11T03:00", tz="Asia/Karachi").json()
    base = f"/api/v1/workspaces/{ctx['workspace_id']}/calendar"

    month = client.get(f"{base}?view=month&date=2027-03-10&timezone=Asia/Karachi").json()
    assert month["view"] == "month" and month["days"][0] == "2027-03-01"
    assert {item["id"] for item in month["items"]} == {fb_post["id"], ig_post["id"]}
    ig_item = next(item for item in month["items"] if item["id"] == ig_post["id"])
    assert ig_item["local_date"] == "2027-03-11" and ig_item["local_time"] == "03:00"
    assert ig_item["status"] == "scheduled" and ig_item["approval_status"] == "approved"
    assert ig_item["brand_name"] == "Brand" and ig_item["account_name"] == "autowok"

    def day_ids(day: str, tz: str) -> list[str]:
        return [item["id"] for item in client.get(f"{base}?view=day&date={day}&timezone={tz}").json()["items"]]

    # 03:00 on the 11th in Karachi is 22:00 UTC on the 10th: the day depends on the viewer's timezone.
    assert day_ids("2027-03-10", "Asia/Karachi") == [fb_post["id"]]
    assert day_ids("2027-03-11", "Asia/Karachi") == [ig_post["id"]]
    assert day_ids("2027-03-10", "UTC") == [fb_post["id"], ig_post["id"]]
    assert day_ids("2027-03-11", "UTC") == []
    week = client.get(f"{base}?view=week&date=2027-03-12&timezone=Asia/Karachi").json()
    assert len(week["days"]) == 7 and len(week["items"]) == 2

    def ids(query: str) -> set[str]:
        return {item["id"] for item in client.get(f"{base}?view=month&date=2027-03-10&timezone=Asia/Karachi{query}").json()["items"]}

    assert ids("&platform=instagram") == {ig_post["id"]}
    assert ids(f"&social_account_id={ctx['fb']}") == {fb_post["id"]}
    assert ids(f"&brand_id={ctx['brand_id']}") == {fb_post["id"], ig_post["id"]}
    other_brand = client.post(f"/api/v1/workspaces/{ctx['workspace_id']}/brands", json={"name": "Empty"}, headers=CSRF).json()
    assert ids(f"&brand_id={other_brand['id']}") == set()
    client.post(f"/api/v1/scheduled-posts/{fb_post['id']}/cancel", headers=CSRF)
    assert ids("&status=cancelled") == {fb_post["id"]}
    assert ids("&status=scheduled") == {ig_post["id"]}

    # Editing the content after scheduling revokes approval; the calendar shows it.
    client.patch(
        f"/api/v1/content/projects/{ctx['project_id']}/drafts/{ctx['drafts']['instagram']}",
        json={"body": "Changed."},
        headers=CSRF,
    )
    changed = next(item for item in client.get(f"{base}?view=month&date=2027-03-10&timezone=Asia/Karachi").json()["items"] if item["id"] == ig_post["id"])
    assert changed["approval_status"] == "draft" and changed["content_changed"] is True

    assert client.get(f"{base}?view=year").status_code == 422
    assert client.get(f"{base}?timezone=Bad/Zone").status_code == 422


# Background scheduling ------------------------------------------------------


def test_due_post_is_published_once_and_future_posts_are_ignored(client, db_factory, token_key):
    ctx = setup(client, db_factory, "sched-due@example.com")
    created = schedule(client, ctx).json()
    row = post_row(db_factory, created["id"])

    assert run_due(db_factory, row.scheduled_at.replace(tzinfo=UTC) - timedelta(minutes=1)) == 0
    assert post_row(db_factory, created["id"]).status == "scheduled"

    at = due_time(row)
    assert run_due(db_factory, at) == 1
    assert run_due(db_factory, at) == 0  # already claimed: processed only once
    queued = post_row(db_factory, created["id"])
    assert queued.status == "queued" and queued.publication_id is not None
    with db_factory() as db:
        jobs = db.query(ContentPublication).filter(ContentPublication.draft_id == UUID(ctx["drafts"]["facebook"])).all()
        assert len(jobs) == 1 and jobs[0].source == "schedule"
        assert jobs[0].idempotency_key == f"schedule:{created['id']}:1"

    fake = FakeMeta(dict(FB_OK))
    assert run_job(db_factory, str(queued.publication_id), fake) == "published"
    published = client.get(f"/api/v1/scheduled-posts/{created['id']}").json()
    assert published["status"] == "published" and published["permalink"] == "https://facebook.com/sched"
    assert [item["action"] for item in published["history"]] == ["created", "queued", "published"]
    assert published["can_edit"] is False
    assert client.post(f"/api/v1/scheduled-posts/{created['id']}/reschedule", json={"scheduled_local": future_local()}, headers=CSRF).status_code == 409
    assert schedule(client, ctx).status_code == 400  # already published to this account
    assert len(fake.calls_to("POST", "/page-1/photos")) == 1


def test_concurrent_schedulers_and_stale_revisions(client, db_factory, token_key):
    ctx = setup(client, db_factory, "sched-race@example.com")
    created = schedule(client, ctx).json()
    row = post_row(db_factory, created["id"])
    at = due_time(row)

    # Two scheduler instances read the same due row; only one claim can succeed.
    with db_factory() as first, db_factory() as second:
        assert schedule_due_posts(first, now=at) == 1
        assert schedule_due_posts(second, now=at) == 0
    with db_factory() as db:
        assert db.query(ContentPublication).count() == 1

    # Reschedule while queued (job not yet started): the old job is cancelled and
    # can never run, and the new revision gets its own job later.
    old_job_id = str(post_row(db_factory, created["id"]).publication_id)
    later = future_local(days=3)
    moved = client.post(f"/api/v1/scheduled-posts/{created['id']}/reschedule", json={"scheduled_local": later}, headers=CSRF)
    assert moved.status_code == 200 and moved.json()["status"] == "scheduled" and moved.json()["revision"] == 2
    with db_factory() as db:
        assert db.get(ContentPublication, UUID(old_job_id)).status == "cancelled"
    assert run_job(db_factory, old_job_id, FakeMeta(dict(FB_OK))) is None
    assert run_due(db_factory, at) == 0
    new_row = post_row(db_factory, created["id"])
    assert run_due(db_factory, due_time(new_row)) == 1
    with db_factory() as db:
        assert db.get(ContentPublication, post_row(db_factory, created["id"]).publication_id).idempotency_key.endswith(":2")


def test_cancellation_races_with_worker(client, db_factory, token_key):
    ctx = setup(client, db_factory, "sched-cancel-race@example.com")
    created = schedule(client, ctx).json()
    row = post_row(db_factory, created["id"])
    run_due(db_factory, due_time(row))
    job_id = post_row(db_factory, created["id"]).publication_id

    # A worker claims the job first: cancellation must now be refused.
    with db_factory() as db:
        assert publishing_service.claim_publication(db, job_id, worker_id="w1") == "pending"
    refused = client.post(f"/api/v1/scheduled-posts/{created['id']}/cancel", headers=CSRF)
    assert refused.status_code == 409 and "being published" in refused.json()["detail"]
    assert client.get(f"/api/v1/scheduled-posts/{created['id']}").json()["status"] == "processing"

    # Cancelled before the worker claims: the job is cancelled and never published.
    ctx2_post = schedule(client, ctx, platform="instagram").json()
    run_due(db_factory, due_time(post_row(db_factory, ctx2_post["id"])))
    ig_job = post_row(db_factory, ctx2_post["id"]).publication_id
    assert client.post(f"/api/v1/scheduled-posts/{ctx2_post['id']}/cancel", headers=CSRF).json()["status"] == "cancelled"
    fake = FakeMeta({("POST", "/ig-1/media"): {"id": "never"}})
    assert run_job(db_factory, str(ig_job), fake) is None
    assert fake.calls == []


def test_cancelled_and_invalidated_posts_are_not_published(client, db_factory, token_key):
    ctx = setup(client, db_factory, "sched-invalid@example.com")
    cancelled = schedule(client, ctx).json()
    client.post(f"/api/v1/scheduled-posts/{cancelled['id']}/cancel", headers=CSRF)
    assert run_due(db_factory, datetime.now(UTC) + timedelta(days=10)) == 0

    invalidated = schedule(client, ctx, platform="instagram").json()
    client.patch(
        f"/api/v1/content/projects/{ctx['project_id']}/drafts/{ctx['drafts']['instagram']}",
        json={"body": "Edited after approval."},
        headers=CSRF,
    )
    assert run_due(db_factory, due_time(post_row(db_factory, invalidated["id"]))) == 1
    failed = client.get(f"/api/v1/scheduled-posts/{invalidated['id']}").json()
    assert failed["status"] == "failed" and failed["publication_id"] is None
    assert "approved" in failed["last_error"]
    assert failed["history"][-1]["action"] == "validation_failed"

    # Re-approving the edited content does not silently revive the old schedule:
    # the version it was created for no longer matches.
    ctx3 = setup(client, db_factory, "sched-version@example.com")
    versioned = schedule(client, ctx3).json()
    client.patch(f"/api/v1/content/projects/{ctx3['project_id']}/drafts/{ctx3['drafts']['facebook']}", json={"body": "v2"}, headers=CSRF)
    submitted = client.post(f"/api/v1/content/projects/{ctx3['project_id']}/submit-for-approval", json={}, headers=CSRF).json()
    client.post(f"/api/v1/content/projects/{ctx3['project_id']}/approvals/{submitted['id']}/decision", json={"status": "approved"}, headers=CSRF)
    run_due(db_factory, due_time(post_row(db_factory, versioned["id"])))
    stale = post_row(db_factory, versioned["id"])
    assert stale.status == "failed" and "changed after" in stale.last_error
    # Rescheduling re-binds to the newly approved version.
    rebound = client.post(f"/api/v1/scheduled-posts/{versioned['id']}/reschedule", json={"scheduled_local": future_local()}, headers=CSRF)
    assert rebound.status_code == 200 and rebound.json()["content_version_number"] == rebound.json()["current_content_version"]


def test_missed_window_after_long_outage(client, db_factory, token_key):
    ctx = setup(client, db_factory, "sched-missed@example.com")
    created = schedule(client, ctx).json()
    row = post_row(db_factory, created["id"])
    run_due(db_factory, row.scheduled_at.replace(tzinfo=UTC) + timedelta(hours=7))
    missed = post_row(db_factory, created["id"])
    assert missed.status == "failed" and "Missed the publishing window" in missed.last_error
    assert missed.publication_id is None


def test_worker_recovers_after_restart_and_redis_interruption(client, db_factory, token_key, isolated_media_environment, monkeypatch):
    ctx = setup(client, db_factory, "sched-recover@example.com")
    created = schedule(client, ctx).json()
    row = post_row(db_factory, created["id"])

    class BrokenRedis:
        def lpush(self, *_args):
            raise redis.ConnectionError("redis restarting")

        def brpop(self, *_args, **_kwargs):
            raise redis.ConnectionError("redis restarting")

    monkeypatch.setattr(redis_module, "redis_client", BrokenRedis())
    sleeps: list[float] = []
    monkeypatch.setattr("app.services.publishing.queue.time.sleep", lambda seconds: sleeps.append(seconds))
    assert wait_for_publication(2) is None and sleeps == [2]

    # The scheduler still creates the job (Redis is only a wake-up signal).
    assert run_due(db_factory, due_time(row)) == 1
    job_id = post_row(db_factory, created["id"]).publication_id

    # Simulate a worker that crashed mid-processing (lease expired, stage before the final call).
    with db_factory() as db:
        job = db.get(ContentPublication, job_id)
        job.status = "processing"
        job.stage = "preparing"
        job.locked_by = "dead-worker"
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
        db.commit()

    fake = FakeMeta(dict(FB_OK))
    monkeypatch.setattr(publishing_service, "MetaPublisher", lambda: fake.publisher())
    tasks: list = []
    worker_tasks.register(tasks)
    assert run_once(db_factory, worker_id="fresh-worker", tasks=tasks) >= 1
    assert post_row(db_factory, created["id"]).status == "published"
    assert len(fake.calls_to("POST", "/page-1/photos")) == 1


def test_worker_loop_runs_scheduler_then_publishes(client, db_factory, token_key, monkeypatch):
    ctx = setup(client, db_factory, "sched-loop@example.com")
    created = schedule(client, ctx).json()
    with db_factory() as db:
        post = db.get(ScheduledPost, UUID(created["id"]))
        post.scheduled_at = datetime.now(UTC) - timedelta(seconds=30)
        db.commit()
    fake = FakeMeta(dict(FB_OK))
    monkeypatch.setattr(publishing_service, "MetaPublisher", lambda: fake.publisher())
    tasks: list = []
    worker_tasks.register(tasks)
    worker_tasks.register(tasks)
    assert len(tasks) == 1
    run_once(db_factory, worker_id="loop", tasks=tasks)
    assert post_row(db_factory, created["id"]).status == "published"


def test_scheduled_publishing_failures_and_retries(client, db_factory, token_key, monkeypatch):
    ctx = setup(client, db_factory, "sched-errors@example.com")

    # Rate limit: the job waits for a retry; the schedule shows it is retrying.
    limited = schedule(client, ctx).json()
    run_due(db_factory, due_time(post_row(db_factory, limited["id"])))
    job_id = str(post_row(db_factory, limited["id"]).publication_id)
    assert run_job(db_factory, job_id, FakeMeta({("POST", "/page-1/photos"): meta_error(400, 4, "Application request limit reached")})) == "pending"
    retrying = client.get(f"/api/v1/scheduled-posts/{limited['id']}").json()
    assert retrying["status"] == "queued" and "rate-limited" in retrying["last_error"]
    assert retrying["history"][-1]["action"] == "retry_scheduled"
    assert retrying["scheduled_at"] == limited["scheduled_at"]  # original time preserved
    later = datetime.now(UTC) + timedelta(days=5)
    assert run_job(db_factory, job_id, FakeMeta(dict(FB_OK)), now=later) == "published"
    assert post_row(db_factory, limited["id"]).status == "published"

    # Expired token: fails, account marked expired, user must reconnect.
    expired = schedule(client, ctx, platform="instagram").json()
    run_due(db_factory, due_time(post_row(db_factory, expired["id"])))
    ig_job = str(post_row(db_factory, expired["id"]).publication_id)
    assert run_job(db_factory, ig_job, FakeMeta({("POST", "/ig-1/media"): meta_error(400, 190, "Error validating access token")})) == "failed"
    detail = client.get(f"/api/v1/scheduled-posts/{expired['id']}").json()
    assert detail["status"] == "failed" and "Reconnect" in detail["last_error"]
    assert detail["account_status"] == "expired" and detail["can_retry"] is True
    assert client.post(f"/api/v1/scheduled-posts/{expired['id']}/retry", json={}, headers=CSRF).status_code == 409
    with db_factory() as db:
        db.get(SocialAccount, UUID(ctx["ig"])).connection_status = "connected"
        db.commit()
    retried = client.post(f"/api/v1/scheduled-posts/{expired['id']}/retry", json={}, headers=CSRF)
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    ig_ok = FakeMeta({
        ("POST", "/ig-1/media"): {"id": "c1"},
        ("GET", "/c1"): {"status_code": "FINISHED"},
        ("GET", "/ig-1/content_publishing_limit"): {"data": []},
        ("POST", "/ig-1/media_publish"): {"id": "m1"},
        ("GET", "/m1"): {"permalink": "https://instagram.com/p/m1"},
    })
    assert run_job(db_factory, ig_job, ig_ok) == "published"
    assert client.get(f"/api/v1/scheduled-posts/{expired['id']}").json()["status"] == "published"


def test_permanent_and_uncertain_failures(client, db_factory, token_key):
    ctx = setup(client, db_factory, "sched-permanent@example.com")
    permanent = schedule(client, ctx).json()
    run_due(db_factory, due_time(post_row(db_factory, permanent["id"])))
    job_id = str(post_row(db_factory, permanent["id"]).publication_id)
    assert run_job(db_factory, job_id, FakeMeta({("POST", "/page-1/photos"): meta_error(400, 368, "Blocked")})) == "failed"
    failed = client.get(f"/api/v1/scheduled-posts/{permanent['id']}").json()
    assert failed["status"] == "failed" and failed["can_retry"] is False
    assert failed["publication"]["error_category"] == "permanent"
    # The slot is released: rescheduling creates a fresh attempt for a new revision.
    rescheduled = client.post(f"/api/v1/scheduled-posts/{permanent['id']}/reschedule", json={"scheduled_local": future_local()}, headers=CSRF)
    assert rescheduled.status_code == 200 and rescheduled.json()["status"] == "scheduled"
    assert rescheduled.json()["publication_id"] is None

    # Timeout on the final Facebook call: uncertain, never retried automatically,
    # and the schedule cannot be changed until the user resolves it.
    run_due(db_factory, due_time(post_row(db_factory, permanent["id"])))
    job2 = str(post_row(db_factory, permanent["id"]).publication_id)
    timeout = FakeMeta({("POST", "/page-1/photos"): httpx.ReadTimeout("timeout")})
    assert run_job(db_factory, job2, timeout) == "failed"
    uncertain = client.get(f"/api/v1/scheduled-posts/{permanent['id']}").json()
    assert uncertain["publication"]["outcome_uncertain"] is True
    assert uncertain["can_edit"] is False
    assert client.post(f"/api/v1/scheduled-posts/{permanent['id']}/reschedule", json={"scheduled_local": future_local()}, headers=CSRF).status_code == 409
    assert client.post(f"/api/v1/scheduled-posts/{permanent['id']}/retry", json={}, headers=CSRF).status_code == 409
    confirmed = client.post(f"/api/v1/scheduled-posts/{permanent['id']}/retry", json={"confirm_not_published": True}, headers=CSRF)
    assert confirmed.status_code == 200
    assert run_job(db_factory, job2, FakeMeta(dict(FB_OK))) == "published"
    assert len(timeout.calls_to("POST", "/page-1/photos")) == 1


def test_queue_status_and_scheduled_history(client, db_factory, token_key):
    ctx = setup(client, db_factory, "sched-queue@example.com")
    first = schedule(client, ctx).json()
    schedule(client, ctx, platform="instagram", local=future_local(days=4))
    run_due(db_factory, due_time(post_row(db_factory, first["id"])))
    queue = client.get(f"/api/v1/workspaces/{ctx['workspace_id']}/publishing/queue").json()
    assert queue["schedule_counts"]["queued"] == 1 and queue["schedule_counts"]["scheduled"] == 1
    assert queue["counts"]["pending"] == 1 and len(queue["active_jobs"]) == 1
    assert len(queue["upcoming"]) == 1 and queue["next_scheduled_at"].endswith("Z")

    history = client.get(f"/api/v1/workspaces/{ctx['workspace_id']}/publishing/jobs?source=schedule").json()
    assert len(history) == 1 and history[0]["source"] == "schedule"
    manual_cancel = client.post(f"/api/v1/publishing/jobs/{history[0]['id']}/cancel", headers=CSRF)
    assert manual_cancel.status_code == 409  # scheduled jobs are managed from the calendar


def test_immediate_publishing_still_works_alongside_schedules(client, db_factory, token_key):
    ctx = setup(client, db_factory, "sched-regression@example.com")
    schedule(client, ctx, platform="instagram")
    response = client.post(
        f"/api/v1/content/drafts/{ctx['drafts']['facebook']}/publish",
        json={"social_account_id": ctx["fb"], "confirm": True},
        headers=CSRF,
    )
    assert response.status_code == 202
    assert run_job(db_factory, response.json()["id"], FakeMeta(dict(FB_OK))) == "published"
    calendar = client.get(f"/api/v1/workspaces/{ctx['workspace_id']}/calendar?view=list&timezone=UTC").json()
    kinds = {item["kind"] for item in calendar["items"]}
    assert kinds == {"scheduled", "published"}
    assert calendar["unscheduled"] == []
