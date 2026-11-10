from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx

from app.models import ContentPublication, PublishingAttempt, SocialAccount
from app.services.publishing.queue import READY_QUEUE_KEY
from app.services.publishing.service import claim_publication, due_publication_ids
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
    mp4_bytes,
    register,
    run_job,
    upload,
)


def setup_workspace(client, db_factory, email: str, *, media_platforms=("facebook", "instagram")):
    register(client, email)
    workspace_id = create_workspace(client)
    image = upload(client, workspace_id, jpeg_bytes(1080, 1080), "post.jpg").json()
    media = {platform: [image["id"]] for platform in media_platforms}
    content = create_approved_content(client, workspace_id, media=media)
    fb = connect_account(db_factory, workspace_id)
    ig = connect_account(db_factory, workspace_id, platform="instagram")
    return workspace_id, content, fb, ig, image


def publish(client, draft_id: str, account_id: str, **extra):
    body = {"social_account_id": account_id, "confirm": True, **extra}
    return client.post(f"/api/v1/content/drafts/{draft_id}/publish", json=body, headers=CSRF)


def get_job(db_factory, job_id: str) -> ContentPublication:
    with db_factory() as db:
        job = db.get(ContentPublication, UUID(job_id))
        db.expunge(job)
        return job


def test_facebook_photo_publishing_success(client, db_factory, token_key, isolated_media_environment):
    workspace_id, content, fb, _ig, image = setup_workspace(client, db_factory, "fb-success@example.com")
    validation = client.post(
        f"/api/v1/content/drafts/{content['drafts']['facebook']}/publishing/validate",
        json={"social_account_id": fb},
        headers=CSRF,
    )
    assert validation.status_code == 200 and validation.json()["eligible"] is True
    assert validation.json()["publish_format"] == "photo"

    response = publish(client, content["drafts"]["facebook"], fb)
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["status"] == "pending"
    assert isolated_media_environment.lists[READY_QUEUE_KEY] == [job["id"]]

    fake = FakeMeta({
        ("POST", "/page-1/photos"): {"id": "photo-1", "post_id": "page-1_post-1"},
        ("GET", "/page-1_post-1"): {"permalink_url": "https://www.facebook.com/page-1/posts/1"},
    })
    assert run_job(db_factory, job["id"], fake) == "published"
    call = fake.calls_to("POST", "/page-1/photos")[0]
    assert call["auth"] == "Bearer page-access-secret"
    assert call["data"]["url"].startswith(f"https://media.autowok.test/api/v1/public-media/{image['id']}?")
    assert "signature=" in call["data"]["url"]
    assert call["data"]["message"].startswith("Big news.")

    detail = client.get(f"/api/v1/publishing/jobs/{job['id']}").json()
    assert detail["status"] == "published"
    assert detail["external_post_id"] == "page-1_post-1"
    assert detail["permalink"] == "https://www.facebook.com/page-1/posts/1"
    assert [attempt["status"] for attempt in detail["attempts"]] == ["succeeded"]
    assert "page-access-secret" not in str(detail)

    history = client.get(f"/api/v1/workspaces/{workspace_id}/publishing/jobs?status=published").json()
    assert [item["id"] for item in history] == [job["id"]]

    duplicate = publish(client, content["drafts"]["facebook"], fb)
    assert duplicate.status_code == 400 and "already published" in duplicate.json()["detail"]


def test_facebook_text_and_multi_photo_formats(client, db_factory, token_key):
    register(client, "fb-formats@example.com")
    workspace_id = create_workspace(client)
    one = upload(client, workspace_id, jpeg_bytes(100, 100, color=(5, 5, 5)), "a.jpg").json()
    two = upload(client, workspace_id, jpeg_bytes(100, 100, color=(6, 6, 6)), "b.jpg").json()
    content = create_approved_content(client, workspace_id, platforms=("facebook",), media={"facebook": [one["id"], two["id"]]})
    fb = connect_account(db_factory, workspace_id)
    job = publish(client, content["drafts"]["facebook"], fb).json()
    fake = FakeMeta({
        ("POST", "/page-1/photos"): [{"id": "p1"}, {"id": "p2"}],
        ("POST", "/page-1/feed"): {"id": "page-1_multi"},
        ("GET", "/page-1_multi"): {"permalink_url": "https://facebook.com/multi"},
    })
    assert run_job(db_factory, job["id"], fake) == "published"
    uploads = fake.calls_to("POST", "/page-1/photos")
    assert [call["data"]["published"] for call in uploads] == ["false", "false"]
    feed = fake.calls_to("POST", "/page-1/feed")[0]["data"]
    assert feed["attached_media[0]"] == '{"media_fbid": "p1"}'
    assert feed["attached_media[1]"] == '{"media_fbid": "p2"}'

    text_only = create_approved_content(client, workspace_id, platforms=("facebook",))
    text_job = publish(client, text_only["drafts"]["facebook"], fb).json()
    text_fake = FakeMeta({("POST", "/page-1/feed"): {"id": "page-1_text"}, ("GET", "/page-1_text"): {}})
    assert run_job(db_factory, text_job["id"], text_fake) == "published"
    assert text_fake.calls_to("POST", "/page-1/feed")[0]["data"]["message"].startswith("Big news.")
    assert get_job(db_factory, text_job["id"]).permalink == "https://www.facebook.com/page-1_text"


def test_instagram_image_and_carousel_publishing(client, db_factory, token_key):
    _workspace_id, content, _fb, ig, _image = setup_workspace(client, db_factory, "ig-success@example.com")
    job = publish(client, content["drafts"]["instagram"], ig).json()
    fake = FakeMeta({
        ("POST", "/ig-1/media"): {"id": "container-1"},
        ("GET", "/container-1"): [{"status_code": "IN_PROGRESS"}, {"status_code": "FINISHED"}],
        ("GET", "/ig-1/content_publishing_limit"): {"data": [{"quota_usage": 3, "config": {"quota_total": 100}}]},
        ("POST", "/ig-1/media_publish"): {"id": "ig-media-1"},
        ("GET", "/ig-media-1"): {"permalink": "https://www.instagram.com/p/abc/"},
    })
    assert run_job(db_factory, job["id"], fake) == "published"
    created = fake.calls_to("POST", "/ig-1/media")[0]["data"]
    assert created["image_url"].startswith("https://media.autowok.test/")
    assert created["caption"].endswith("#launch")
    assert fake.calls_to("POST", "/ig-1/media_publish")[0]["data"] == {"creation_id": "container-1"}
    stored = get_job(db_factory, job["id"])
    assert stored.external_container_id == "container-1"
    assert stored.external_post_id == "ig-media-1"
    assert stored.permalink == "https://www.instagram.com/p/abc/"

    workspace_id = str(stored.workspace_id)
    video = upload(client, workspace_id, mp4_bytes(), "clip.mp4").json()
    second = upload(client, workspace_id, jpeg_bytes(1080, 1080, color=(9, 9, 9)), "second.jpg").json()
    carousel = create_approved_content(client, workspace_id, platforms=("instagram",), media={"instagram": [second["id"], video["id"]]})
    carousel_job = publish(client, carousel["drafts"]["instagram"], ig).json()
    carousel_fake = FakeMeta({
        ("POST", "/ig-1/media"): [{"id": "child-1"}, {"id": "child-2"}, {"id": "parent-1"}],
        ("GET", "/child-1"): {"status_code": "FINISHED"},
        ("GET", "/child-2"): [{"status_code": "IN_PROGRESS"}, {"status_code": "FINISHED"}],
        ("GET", "/parent-1"): {"status_code": "FINISHED"},
        ("GET", "/ig-1/content_publishing_limit"): {"data": []},
        ("POST", "/ig-1/media_publish"): {"id": "ig-carousel"},
        ("GET", "/ig-carousel"): {"permalink": "https://www.instagram.com/p/car/"},
    })
    assert run_job(db_factory, carousel_job["id"], carousel_fake) == "published"
    items = [call["data"] for call in carousel_fake.calls_to("POST", "/ig-1/media")]
    assert items[0]["is_carousel_item"] == "true" and "image_url" in items[0]
    assert items[1]["media_type"] == "VIDEO" and "video_url" in items[1]
    assert items[2]["media_type"] == "CAROUSEL" and items[2]["children"] == "child-1,child-2"


def test_meta_rejection_token_expiry_and_processing_failures(client, db_factory, token_key):
    workspace_id, content, fb, ig, _image = setup_workspace(client, db_factory, "ig-fail@example.com")

    rejected = publish(client, content["drafts"]["facebook"], fb).json()
    fake = FakeMeta({("POST", "/page-1/photos"): meta_error(400, 100, "Invalid parameter")})
    assert run_job(db_factory, rejected["id"], fake) == "failed"
    job = client.get(f"/api/v1/publishing/jobs/{rejected['id']}").json()
    assert job["error_category"] == "invalid_content"
    assert "Invalid parameter" in job["error_message"]
    assert job["requires_user_action"] is True and job["can_retry"] is True
    assert job["attempt_count"] == 1  # permanent errors are not auto-retried

    expired = publish(client, content["drafts"]["instagram"], ig).json()
    token_fake = FakeMeta({("POST", "/ig-1/media"): meta_error(400, 190, "Session has expired")})
    assert run_job(db_factory, expired["id"], token_fake) == "failed"
    assert get_job(db_factory, expired["id"]).error_category == "token_expired"
    with db_factory() as db:
        assert db.get(SocialAccount, UUID(ig)).connection_status == "expired"
    blocked = client.post(f"/api/v1/publishing/jobs/{expired['id']}/retry", json={}, headers=CSRF)
    assert blocked.status_code == 409 and "Reconnect" in blocked.json()["detail"]

    ig2 = connect_account(db_factory, workspace_id, platform="instagram", platform_account_id="ig-2")
    processing = publish(client, content["drafts"]["instagram"], ig2).json()
    error_fake = FakeMeta({
        ("POST", "/ig-2/media"): {"id": "bad-container"},
        ("GET", "/bad-container"): {"status_code": "ERROR"},
    })
    assert run_job(db_factory, processing["id"], error_fake) == "failed"
    failed = get_job(db_factory, processing["id"])
    assert failed.error_category == "invalid_media"
    assert failed.active_guard is None
    assert error_fake.calls_to("POST", "/ig-2/media_publish") == []


def test_temporary_errors_retry_with_backoff_then_succeed(client, db_factory, token_key):
    _workspace_id, content, _fb, ig, _image = setup_workspace(client, db_factory, "retry@example.com")
    job = publish(client, content["drafts"]["instagram"], ig).json()
    fake = FakeMeta({
        ("POST", "/ig-1/media"): [httpx.Response(500, json={"error": {"code": 2, "message": "Service temporarily unavailable", "is_transient": True}}), {"id": "container-r"}],
        ("GET", "/container-r"): {"status_code": "FINISHED"},
        ("GET", "/ig-1/content_publishing_limit"): {"data": []},
        ("POST", "/ig-1/media_publish"): {"id": "media-r"},
        ("GET", "/media-r"): {},
    })
    assert run_job(db_factory, job["id"], fake) == "pending"
    waiting = get_job(db_factory, job["id"])
    assert waiting.error_category == "platform_temporary"
    retry_at = waiting.next_attempt_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    assert now + timedelta(seconds=14) <= retry_at <= now + timedelta(seconds=31)
    with db_factory() as db:
        assert UUID(job["id"]) not in due_publication_ids(db)
        assert UUID(job["id"]) in due_publication_ids(db, now=retry_at + timedelta(seconds=1))
    assert run_job(db_factory, job["id"], fake, now=retry_at + timedelta(seconds=1)) == "published"
    with db_factory() as db:
        attempts = db.query(PublishingAttempt).filter(PublishingAttempt.publication_id == UUID(job["id"])).order_by(PublishingAttempt.attempt_number).all()
        assert [item.status for item in attempts] == ["failed", "succeeded"]


def test_rate_limit_exhausts_attempts_then_requires_user_retry(client, db_factory, token_key, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "publishing_max_attempts", 2)
    _workspace_id, content, fb, _ig, _image = setup_workspace(client, db_factory, "ratelimit@example.com")
    job = publish(client, content["drafts"]["facebook"], fb).json()
    fake = FakeMeta({("POST", "/page-1/photos"): meta_error(400, 32, "Page request limit reached")})
    assert run_job(db_factory, job["id"], fake) == "pending"
    rate_wait = get_job(db_factory, job["id"])
    assert rate_wait.error_category == "rate_limited"
    assert rate_wait.next_attempt_at.replace(tzinfo=timezone.utc) >= datetime.now(timezone.utc) + timedelta(seconds=140)
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    assert run_job(db_factory, job["id"], fake, now=later) == "failed"
    final = client.get(f"/api/v1/publishing/jobs/{job['id']}").json()
    assert final["requires_user_action"] is True and final["can_retry"] is True
    retried = client.post(f"/api/v1/publishing/jobs/{job['id']}/retry", json={}, headers=CSRF)
    assert retried.status_code == 200 and retried.json()["status"] == "pending"


def test_facebook_timeout_on_final_call_is_uncertain_and_never_auto_retried(client, db_factory, token_key):
    _workspace_id, content, fb, _ig, _image = setup_workspace(client, db_factory, "uncertain@example.com")
    job = publish(client, content["drafts"]["facebook"], fb).json()
    fake = FakeMeta({("POST", "/page-1/photos"): httpx.ReadTimeout("timed out")})
    assert run_job(db_factory, job["id"], fake) == "failed"
    stored = get_job(db_factory, job["id"])
    assert stored.outcome_uncertain is True and stored.error_category == "uncertain"
    assert stored.active_guard is not None  # still guarded against duplicates
    assert len(fake.calls_to("POST", "/page-1/photos")) == 1

    again = publish(client, content["drafts"]["facebook"], fb)
    assert again.status_code == 400 and "unconfirmed result" in again.json()["detail"]
    blind_retry = client.post(f"/api/v1/publishing/jobs/{job['id']}/retry", json={}, headers=CSRF)
    assert blind_retry.status_code == 409 and "may already have been published" in blind_retry.json()["detail"]
    confirmed = client.post(f"/api/v1/publishing/jobs/{job['id']}/retry", json={"confirm_not_published": True}, headers=CSRF)
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "pending"
    success = FakeMeta({("POST", "/page-1/photos"): {"id": "x", "post_id": "page-1_ok"}, ("GET", "/page-1_ok"): {}})
    assert run_job(db_factory, job["id"], success) == "published"


def test_instagram_timeout_on_media_publish_recovers_without_duplicate(client, db_factory, token_key):
    _workspace_id, content, _fb, ig, _image = setup_workspace(client, db_factory, "ig-timeout@example.com")
    job = publish(client, content["drafts"]["instagram"], ig).json()
    first = FakeMeta({
        ("POST", "/ig-1/media"): {"id": "container-t"},
        ("GET", "/container-t"): {"status_code": "FINISHED"},
        ("GET", "/ig-1/content_publishing_limit"): {"data": []},
        ("POST", "/ig-1/media_publish"): httpx.ReadTimeout("timed out"),
    })
    assert run_job(db_factory, job["id"], first) == "pending"
    assert get_job(db_factory, job["id"]).external_container_id == "container-t"

    # Meta actually published it: the container now reports PUBLISHED.
    second = FakeMeta({("GET", "/container-t"): {"status_code": "PUBLISHED"}})
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    assert run_job(db_factory, job["id"], second, now=later) == "published"
    assert second.calls_to("POST", "/ig-1/media_publish") == []
    assert second.calls_to("POST", "/ig-1/media") == []


def test_idempotency_concurrency_and_worker_crash_recovery(client, db_factory, token_key):
    _workspace_id, content, fb, ig, _image = setup_workspace(client, db_factory, "idempotent@example.com")
    first = publish(client, content["drafts"]["facebook"], fb, idempotency_key="click-0001")
    second = publish(client, content["drafts"]["facebook"], fb, idempotency_key="click-0001")
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    different = publish(client, content["drafts"]["facebook"], fb, idempotency_key="click-0002")
    assert different.status_code == 400 and "already in progress" in different.json()["detail"]
    reused = publish(client, content["drafts"]["instagram"], ig, idempotency_key="click-0001")
    assert reused.status_code == 409

    job_id = UUID(first.json()["id"])
    with db_factory() as db:
        assert claim_publication(db, job_id, worker_id="worker-a") == "pending"
    with db_factory() as db:
        assert claim_publication(db, job_id, worker_id="worker-b") is None

    # Simulate worker-a crashing after it sent the final Facebook request.
    with db_factory() as db:
        job = db.get(ContentPublication, job_id)
        job.status = "publishing"
        job.stage = "publishing"
        job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    fake = FakeMeta({("POST", "/page-1/photos"): {"id": "should-not-be-called"}})
    assert run_job(db_factory, str(job_id), fake, worker_id="worker-b") == "failed"
    assert fake.calls == []
    recovered = get_job(db_factory, str(job_id))
    assert recovered.outcome_uncertain is True and recovered.error_code == "worker_interrupted"


def test_publishing_authorization_and_eligibility_rules(client, client_factory, db_factory, token_key):
    workspace_id, content, fb, _ig, _image = setup_workspace(client, db_factory, "auth-owner@example.com")
    unapproved = create_approved_content(client, workspace_id, platforms=("facebook",), approve=False)
    response = publish(client, unapproved["drafts"]["facebook"], fb)
    assert response.status_code == 400 and "approved" in response.json()["detail"]

    not_confirmed = client.post(
        f"/api/v1/content/drafts/{content['drafts']['facebook']}/publish",
        json={"social_account_id": fb, "confirm": False},
        headers=CSRF,
    )
    assert not_confirmed.status_code == 400

    disconnected = connect_account(db_factory, workspace_id, platform_account_id="page-off", status="disconnected")
    assert "disconnected" in publish(client, content["drafts"]["facebook"], disconnected).json()["detail"]
    no_scope = connect_account(db_factory, workspace_id, platform_account_id="page-noscope", scopes=["pages_show_list"])
    assert "pages_manage_posts" in publish(client, content["drafts"]["facebook"], no_scope).json()["detail"]
    personal = connect_account(db_factory, workspace_id, platform="instagram", platform_account_id="ig-personal", account_type="PERSONAL")
    assert "Professional" in publish(client, content["drafts"]["instagram"], personal).json()["detail"]

    with client_factory() as member:
        register(member, "auth-member@example.com")
        add_member(client, workspace_id, "auth-member@example.com")
        assert publish(member, content["drafts"]["facebook"], fb).status_code == 403
        validate = member.post(
            f"/api/v1/content/drafts/{content['drafts']['facebook']}/publishing/validate",
            json={"social_account_id": fb},
            headers=CSRF,
        ).json()
        assert validate["eligible"] is False

    with client_factory() as outsider:
        register(outsider, "auth-outsider@example.com")
        other_workspace = create_workspace(outsider, "Outsider")
        assert publish(outsider, content["drafts"]["facebook"], fb).status_code == 404
        assert outsider.get(f"/api/v1/workspaces/{workspace_id}/publishing/jobs").status_code == 404
        foreign_account = connect_account(db_factory, other_workspace, platform_account_id="page-foreign")
    assert publish(client, content["drafts"]["facebook"], foreign_account).status_code == 404

    job = publish(client, content["drafts"]["facebook"], fb).json()
    with client_factory() as outsider:
        register(outsider, "auth-outsider2@example.com")
        assert outsider.get(f"/api/v1/publishing/jobs/{job['id']}").status_code == 404
        assert outsider.post(f"/api/v1/publishing/jobs/{job['id']}/cancel", headers=CSRF).status_code == 404
    cancelled = client.post(f"/api/v1/publishing/jobs/{job['id']}/cancel", headers=CSRF)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert run_job(db_factory, job["id"], FakeMeta()) is None
    # After cancellation the account can be published to again.
    assert publish(client, content["drafts"]["facebook"], fb).status_code == 202


def test_worker_revalidates_approval_before_publishing(client, db_factory, token_key):
    _workspace_id, content, fb, _ig, _image = setup_workspace(client, db_factory, "revalidate@example.com")
    job = publish(client, content["drafts"]["facebook"], fb).json()
    edited = client.patch(
        f"/api/v1/content/projects/{content['project_id']}/drafts/{content['drafts']['facebook']}",
        json={"body": "Changed after approval."},
        headers=CSRF,
    )
    assert edited.status_code == 200
    fake = FakeMeta({("POST", "/page-1/photos"): {"id": "nope"}})
    assert run_job(db_factory, job["id"], fake) == "failed"
    assert fake.calls == []
    failed = get_job(db_factory, job["id"])
    assert failed.error_category == "validation" and "approved" in failed.error_message


def test_worker_loop_processes_queue_and_database_due_jobs(client, db_factory, token_key, isolated_media_environment, monkeypatch):
    _workspace_id, content, fb, _ig, _image = setup_workspace(client, db_factory, "worker-loop@example.com")
    job = publish(client, content["drafts"]["facebook"], fb).json()
    isolated_media_environment.lists.clear()  # simulate Redis losing the message
    fake = FakeMeta({("POST", "/page-1/photos"): {"id": "w", "post_id": "page-1_w"}, ("GET", "/page-1_w"): {}})
    from app.services.publishing import service as service_module

    monkeypatch.setattr(service_module, "MetaPublisher", lambda: fake.publisher())
    processed = run_once(db_factory, worker_id="loop-worker")
    assert processed == 1
    assert get_job(db_factory, job["id"]).status == "published"
    assert run_once(db_factory, worker_id="loop-worker") == 0
