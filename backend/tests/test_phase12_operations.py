"""Phase 12 operations: health checks, metrics, error reporting, worker
behaviour and crash recovery. In-memory fakes only (SQLite, FakeRedis, mocked
Meta); no real service is contacted."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError

from app.core import error_reporting, metrics
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models import AnalyticsSyncJob, ContentPublication, PublishingAttempt, ScheduledPost
from app.services.publishing import service as publishing_service
from app.services.publishing.queue import READY_QUEUE_KEY, wait_for_publication
from app.worker import beat, healthcheck, run_once
from tests.publishing_helpers import (
    CSRF,
    FakeMeta,
    connect_account,
    create_approved_content,
    create_workspace,
    register,
    run_job,
)

FB_TEXT_OK = {("POST", "/page-1/feed"): {"id": "page-1_post"}, ("GET", "/page-1_post"): {"permalink_url": "https://facebook.com/p"}}


def queued_job(client, db_factory) -> str:
    """An approved text post with a pending publishing job. Returns the job id."""
    register(client, f"ops-{datetime.now(UTC).timestamp()}@example.com")
    workspace_id = create_workspace(client)
    content = create_approved_content(client, workspace_id, platforms=("facebook",))
    account = connect_account(db_factory, workspace_id)
    response = client.post(
        f"/api/v1/content/drafts/{content['drafts']['facebook']}/publish",
        json={"social_account_id": account, "confirm": True},
        headers=CSRF,
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


def abandon(db_factory, job_id: str, *, stage: str, **fields) -> None:
    """Put a job in the state a killed worker leaves behind."""
    with db_factory() as db:
        job = db.get(ContentPublication, UUID(job_id))
        job.status = "publishing" if stage in {"publishing", "done"} else "processing"
        job.stage = stage
        job.locked_by = "dead-worker"
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
        job.attempt_count = max(job.attempt_count, 1)
        for key, value in fields.items():
            setattr(job, key, value)
        db.add(PublishingAttempt(publication_id=job.id, attempt_number=job.attempt_count, status="running", worker_id="dead-worker"))
        db.commit()


def job_row(db_factory, job_id: str) -> ContentPublication:
    with db_factory() as db:
        job = db.get(ContentPublication, UUID(job_id))
        db.expunge(job)
        return job


# Health ----------------------------------------------------------------------------


def test_liveness_never_touches_dependencies(client_factory):
    class Broken:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("liveness must not query the database")

        def close(self):
            pass

    client = client_factory()
    app.dependency_overrides[get_db] = lambda: Broken()
    for path in ("/api/v1/health", "/api/v1/health/live"):
        response = client.get(path)
        assert response.status_code == 200 and response.json()["status"] == "ok"


def test_readiness_is_503_when_a_dependency_is_down(client_factory, monkeypatch):
    from app.api.v1.routes import health

    client = client_factory()
    assert client.get("/api/v1/ready").status_code == 200

    monkeypatch.setattr(health, "ping_redis", lambda: False)
    degraded = client.get("/api/v1/ready")
    assert degraded.status_code == 503
    assert degraded.json() == {"status": "degraded", "service": "Autowok", "dependencies": {"database": True, "redis": False}}

    class Down:
        def execute(self, *_args, **_kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection to server at 10.0.0.7 refused, password=secret"))

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(health, "ping_redis", lambda: True)
    app.dependency_overrides[get_db] = lambda: Down()
    down = client.get("/api/v1/ready")
    assert down.status_code == 503 and down.json()["dependencies"] == {"database": False, "redis": True}
    assert "10.0.0.7" not in down.text and "secret" not in down.text


def test_monitoring_endpoints_require_the_token_when_configured(client, monkeypatch):
    from app.api.v1.routes import health

    assert client.get("/api/v1/health/details").status_code == 200  # development without a token
    monkeypatch.setattr(health.settings, "metrics_token", "m" * 32)
    assert client.get("/api/v1/health/details").status_code == 401
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    details = client.get("/api/v1/health/details", headers={"Authorization": f"Bearer {'m' * 32}"})
    assert details.status_code == 200
    body = details.json()
    assert set(body) == {"status", "dependencies", "worker", "external", "error_reporting"}
    assert body["worker"] == {"alive": 0, "available": False}
    assert all(isinstance(value, bool) for value in body["external"].values())  # presence only, never values
    # In production an unset token hides the endpoints instead of opening them.
    monkeypatch.setattr(health.settings, "metrics_token", "")
    monkeypatch.setattr(health.settings, "app_env", "production")
    assert client.get("/metrics").status_code == 404


def test_worker_heartbeat_is_reported(client, isolated_media_environment, tmp_path, monkeypatch):
    fake = isolated_media_environment
    store: dict[str, str] = {}
    fake.set = lambda key, value, ex=None: store.__setitem__(key, value)  # type: ignore[attr-defined]
    fake.scan_iter = lambda match=None, count=None: iter(list(store))  # type: ignore[attr-defined]
    settings = get_settings()
    heartbeat_file = tmp_path / "worker.heartbeat"
    monkeypatch.setattr(settings, "worker_heartbeat_file", str(heartbeat_file))
    assert healthcheck() == 1  # no heartbeat yet
    beat("worker-a", settings)
    assert healthcheck() == 0 and heartbeat_file.exists()
    assert client.get("/api/v1/health/details").json()["worker"] == {"alive": 1, "available": True}
    # A stale heartbeat file means the worker is not making progress.
    old = time.time() - settings.worker_heartbeat_ttl_seconds - 10
    import os

    os.utime(heartbeat_file, (old, old))
    assert healthcheck() == 1


# Metrics and error reporting -------------------------------------------------------


def test_metrics_expose_operations_without_identifiers(client, db_factory, monkeypatch):
    monkeypatch.setattr(app.router, "lifespan_context", app.router.lifespan_context)
    register(client, "metrics@example.com")
    workspace_id = create_workspace(client)
    client.get(f"/api/v1/workspaces/{workspace_id}/brands")
    client.get("/api/v1/workspaces/00000000-0000-0000-0000-000000000000")  # a 404

    import app.main as main_module

    monkeypatch.setattr(main_module, "SessionLocal", db_factory)
    metrics._cache["at"] = 0.0
    response = client.get("/metrics")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/plain")
    text = response.text
    assert 'autowok_http_requests_total{method="GET",route="/api/v1/workspaces/{workspace_id}/brands",status="200"}' in text
    assert 'route="/api/v1/workspaces/{workspace_id}",status="404"' in text
    assert "autowok_http_request_duration_seconds_bucket" in text
    assert 'autowok_queue_depth{queue="publishing"}' in text and 'autowok_queue_depth{queue="agent_workflows"}' in text
    assert "autowok_workers_alive" in text and "autowok_dependency_up" in text
    # No tenant or user data: ids and emails never become label values.
    assert workspace_id not in text and "metrics@example.com" not in text


def test_error_reports_go_through_one_interface_with_categories():
    captured: list[dict] = []

    class Recorder:
        def capture(self, *, category, message, exc, fields):
            captured.append({"category": category, "message": message, "exc": exc, "fields": fields})

    before = metrics.ERRORS.labels(category="ai_provider")._value.get()
    error_reporting.set_reporter(Recorder())
    try:
        error_reporting.report_error("ai_provider", "Groq failed", RuntimeError("boom"), model="m")
    finally:
        error_reporting.set_reporter(error_reporting.LogReporter())
    assert captured[0]["category"] == "ai_provider" and captured[0]["fields"] == {"model": "m"}
    assert metrics.ERRORS.labels(category="ai_provider")._value.get() == before + 1


def test_sentry_is_optional_and_never_claimed_without_the_sdk(monkeypatch):
    import builtins

    settings = get_settings()
    monkeypatch.setattr(settings, "sentry_dsn", "")
    assert error_reporting.configure_error_reporting(settings) == "log"
    real_import = builtins.__import__

    def no_sentry(name, *args, **kwargs):
        if name == "sentry_sdk":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sentry)
    monkeypatch.setattr(settings, "sentry_dsn", "https://key@example.invalid/1")
    assert error_reporting.configure_error_reporting(settings) == "sentry-unavailable"
    monkeypatch.setattr(settings, "sentry_dsn", "")
    assert error_reporting.configure_error_reporting(settings) == "log"


def test_groq_and_meta_calls_are_measured():
    def value(counter, **labels):
        return counter.labels(**labels)._value.get()

    before_ai = value(metrics.AI_REQUESTS, operation="completion", outcome="ok")
    before_tokens = value(metrics.AI_TOKENS, kind="prompt")
    metrics.observe_ai("completion", "ok", 0.42, {"prompt_tokens": 120, "completion_tokens": 30})
    assert value(metrics.AI_REQUESTS, operation="completion", outcome="ok") == before_ai + 1
    assert value(metrics.AI_TOKENS, kind="prompt") == before_tokens + 120

    fake = FakeMeta({("GET", "/me"): {"id": "1"}})
    before_meta = value(metrics.EXTERNAL_CALLS, service="meta", outcome="ok")
    with fake.publisher()._graph_factory() as graph:  # the same client the publisher uses
        graph.get("/me", "token")
    assert value(metrics.EXTERNAL_CALLS, service="meta", outcome="ok") == before_meta + 1


# Worker loop -----------------------------------------------------------------------


def test_worker_runs_the_scheduler_first_then_publishing_then_other_tasks(db_factory, monkeypatch):
    order: list[str] = []

    def scheduler(_db):
        order.append("scheduler")
        return 0

    scheduler.before_publishing = True

    def slow(_db):
        order.append("slow")
        return 0

    def other(_db):
        order.append("other")
        return 0

    monkeypatch.setattr("app.worker.due_publication_ids", lambda _db, limit=20: order.append("publishing") or [])
    run_once(db_factory, worker_id="w", tasks=[slow, other, scheduler])
    assert order == ["scheduler", "publishing", "slow", "other"]


def test_worker_task_budget_rotates_so_no_task_starves(db_factory, monkeypatch):
    monkeypatch.setattr("app.worker.due_publication_ids", lambda _db, limit=20: [])
    ran: list[str] = []

    def make(name):
        def task(_db):
            ran.append(name)
            return 1

        task.__name__ = name
        return task

    tasks = [make("a"), make("b"), make("c")]
    state: dict = {}
    # A zero budget lets no periodic task start; nothing is lost, they run next time.
    assert run_once(db_factory, worker_id="w", tasks=tasks, task_budget_seconds=0, state=state) == 0
    assert ran == []
    clock = iter([0.0, 0.0, 10.0, 10.0, 10.0, 10.0])
    monkeypatch.setattr("app.worker.time.monotonic", lambda: next(clock, 10.0))
    run_once(db_factory, worker_id="w", tasks=tasks, task_budget_seconds=5, state=state)
    assert ran == ["a"]  # budget used up after the first task
    monkeypatch.setattr("app.worker.time.monotonic", time.monotonic)
    run_once(db_factory, worker_id="w", tasks=tasks, task_budget_seconds=60, state=state)
    assert ran == ["a", "b", "c", "a"]  # continues where it stopped


def test_worker_throttles_housekeeping_and_survives_task_failures(db_factory, monkeypatch):
    monkeypatch.setattr("app.worker.due_publication_ids", lambda _db, limit=20: [])
    calls = {"housekeeping": 0, "after": 0}

    def housekeeping(_db):
        calls["housekeeping"] += 1
        return 0

    housekeeping.min_interval_seconds = 3600

    def failing(_db):
        raise RuntimeError("task bug")

    def after(_db):
        calls["after"] += 1
        return 2

    state: dict = {}
    assert run_once(db_factory, worker_id="w", tasks=[housekeeping, failing, after], state=state) == 2
    assert run_once(db_factory, worker_id="w", tasks=[housekeeping, failing, after], state=state) == 2
    assert calls == {"housekeeping": 1, "after": 2}  # throttled; the failure did not stop the next task


def test_worker_stops_before_starting_new_work(db_factory, monkeypatch):
    started: list[str] = []
    monkeypatch.setattr("app.worker.due_publication_ids", lambda _db, limit=20: started.append("publishing") or [])
    assert run_once(db_factory, worker_id="w", tasks=[lambda _db: started.append("task") or 1], should_stop=lambda: True) == 0
    assert started == ["publishing"]  # no periodic task was started after the stop signal


def test_wake_up_wait_returns_hint_and_honours_stop(isolated_media_environment):
    fake = isolated_media_environment
    fake.lpush(READY_QUEUE_KEY, "job-1")
    assert wait_for_publication(5) == "job-1"
    started = time.monotonic()
    assert wait_for_publication(30, should_stop=lambda: True) is None
    assert wait_for_publication(30) is None  # a client that does not block must not spin for 30 s
    assert time.monotonic() - started < 2


# Crash recovery --------------------------------------------------------------------


def test_post_created_before_a_crash_is_never_published_twice(client, db_factory, token_key):
    job_id = queued_job(client, db_factory)
    # The worker posted to Facebook and stored the id, then died before marking the job published.
    abandon(db_factory, job_id, stage="done", external_post_id="page-1_post")
    fake = FakeMeta({})  # any request to Meta would be answered with an error
    assert run_job(db_factory, job_id, fake, worker_id="fresh-worker") == "published"
    assert fake.calls == []  # nothing was sent again
    job = job_row(db_factory, job_id)
    assert job.external_post_id == "page-1_post" and job.published_at is not None and job.locked_by is None
    with db_factory() as db:
        statuses = sorted(row.status for row in db.query(PublishingAttempt).filter(PublishingAttempt.publication_id == job.id))
    assert statuses == ["failed", "succeeded"]  # the interrupted attempt was closed


def test_interrupted_final_request_is_uncertain_and_not_retried(client, db_factory, token_key):
    job_id = queued_job(client, db_factory)
    abandon(db_factory, job_id, stage="publishing")
    fake = FakeMeta(dict(FB_TEXT_OK))
    assert run_job(db_factory, job_id, fake, worker_id="fresh-worker") == "failed"
    job = job_row(db_factory, job_id)
    assert fake.calls == [] and job.outcome_uncertain and job.requires_user_action and job.active_guard is not None


def test_job_abandoned_repeatedly_is_stopped(client, db_factory, token_key):
    job_id = queued_job(client, db_factory)
    with db_factory() as db:
        max_attempts = db.get(ContentPublication, UUID(job_id)).max_attempts
    abandon(db_factory, job_id, stage="preparing", attempt_count=max_attempts)
    fake = FakeMeta(dict(FB_TEXT_OK))
    assert run_job(db_factory, job_id, fake, worker_id="fresh-worker") == "failed"
    job = job_row(db_factory, job_id)
    assert fake.calls == [] and job.error_code == "attempts_exhausted" and job.requires_user_action


def test_answer_without_an_id_on_the_final_request_is_uncertain(client, db_factory, token_key):
    job_id = queued_job(client, db_factory)
    fake = FakeMeta({("POST", "/page-1/feed"): {"success": True}})
    assert run_job(db_factory, job_id, fake) == "failed"
    job = job_row(db_factory, job_id)
    assert job.outcome_uncertain and job.status == "failed" and len(fake.calls_to("POST", "/page-1/feed")) == 1


def test_worker_that_lost_its_lease_stops_without_writing(client, db_factory, token_key):
    job_id = queued_job(client, db_factory)

    def taken_over(_request, _data):
        # While this worker waits for Meta, its lease expires and another worker claims the job.
        with db_factory() as db:
            job = db.get(ContentPublication, UUID(job_id))
            job.locked_by = "other-worker"
            db.commit()
        return {"id": "page-1_post"}

    fake = FakeMeta({("POST", "/page-1/feed"): taken_over})
    # The next checkpoint notices the job is no longer owned and stops without writing.
    assert run_job(db_factory, job_id, fake, worker_id="worker-1") is None
    job = job_row(db_factory, job_id)
    assert job.locked_by == "other-worker" and job.status != "published" and job.external_post_id is None


def test_one_broken_scheduled_post_does_not_block_the_others(client, db_factory, token_key, monkeypatch):
    from app.services.scheduling import service as scheduling_service
    from tests.test_phase8_scheduling import post_row, schedule, setup

    ctx = setup(client, db_factory, "sched-ops@example.com")
    first = schedule(client, ctx, platform="facebook").json()
    second = schedule(client, ctx, platform="instagram").json()
    with db_factory() as db:
        for index, created in enumerate((first, second)):
            post = db.get(ScheduledPost, UUID(created["id"]))
            post.scheduled_at = datetime.now(UTC) - timedelta(seconds=60 - index)
        db.commit()
    real = scheduling_service.evaluate_eligibility

    def flaky(db, *, draft, **kwargs):
        if str(draft.id) == ctx["drafts"]["facebook"]:
            raise RuntimeError("unexpected data")
        return real(db, draft=draft, **kwargs)

    monkeypatch.setattr(scheduling_service, "evaluate_eligibility", flaky)
    with db_factory() as db:
        assert scheduling_service.schedule_due_posts(db) == 2
    broken, healthy = post_row(db_factory, first["id"]), post_row(db_factory, second["id"])
    assert broken.status == "failed" and broken.active_guard is None and "unexpected error" in broken.last_error
    assert healthy.status == "queued" and healthy.publication_id is not None


def test_finished_job_is_reconciled_onto_its_scheduled_post(client, db_factory, token_key):
    from app.services.scheduling import service as scheduling_service
    from tests.test_phase8_scheduling import due_time, post_row, run_due, schedule, setup

    ctx = setup(client, db_factory, "reconcile@example.com")
    created = schedule(client, ctx).json()
    row = post_row(db_factory, created["id"])
    assert run_due(db_factory, due_time(row)) == 1
    job_id = post_row(db_factory, created["id"]).publication_id
    # The job finished but the worker died before the post was updated.
    with db_factory() as db:
        job = db.get(ContentPublication, job_id)
        job.status = "published"
        job.published_at = datetime.now(UTC)
        job.external_post_id = "page-1_sched"
        db.commit()
    assert post_row(db_factory, created["id"]).status == "queued"
    with db_factory() as db:
        assert scheduling_service.reconcile_scheduled_posts(db) == 1
        assert scheduling_service.reconcile_scheduled_posts(db) == 0
    assert post_row(db_factory, created["id"]).status == "published"


def test_analytics_job_never_stays_running_after_an_unexpected_error(client, db_factory, token_key):
    from app.services.analytics import sync
    from tests.test_phase9_analytics import setup as analytics_setup

    ctx = analytics_setup(client, db_factory, "sync-ops@example.com", instagram=False)
    account_id = ctx["fb"]
    with db_factory() as db:
        from app.models import User

        job = sync.request_sync(
            db, account=db.get(sync.SocialAccount, UUID(account_id)), requested_by=db.query(User).first().id, enqueue=False
        )
        job_id = job.id

    class Exploding:
        def __enter__(self):
            raise RuntimeError("driver bug")

        def __exit__(self, *_):
            return False

    with db_factory() as db:
        assert sync.process_sync_job(db, job_id, worker_id="w", graph_factory=Exploding) == "failed"
    with db_factory() as db:
        job = db.get(AnalyticsSyncJob, job_id)
        assert job.status == "failed" and job.active_guard is None and job.error_code == "unexpected_error"
        # A job reclaimed after repeated interruptions is stopped as well.
        job.status = "running"
        job.attempt_count = job.max_attempts
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
        job.active_guard = f"account:{account_id}"
        db.commit()
    with db_factory() as db:
        assert sync.process_sync_job(db, job_id, worker_id="w", graph_factory=Exploding) == "failed"
        assert db.get(AnalyticsSyncJob, job_id).error_code == "attempts_exhausted"


def test_due_jobs_that_were_never_attempted_come_first(client, db_factory, token_key):
    job_id = queued_job(client, db_factory)
    with db_factory() as db:
        fresh = db.get(ContentPublication, UUID(job_id))
        retry = ContentPublication(
            workspace_id=fresh.workspace_id,
            project_id=fresh.project_id,
            draft_id=fresh.draft_id,
            social_account_id=fresh.social_account_id,
            platform=fresh.platform,
            idempotency_key="retry-key",
            status="pending",
            attempt_count=1,
            next_attempt_at=datetime.now(UTC) - timedelta(minutes=5),
            created_at=fresh.created_at - timedelta(hours=1),
        )
        db.add(retry)
        db.commit()
        ordered = publishing_service.due_publication_ids(db)
    assert ordered[0] == UUID(job_id)


@pytest.mark.parametrize("name", ["scheduling", "analytics", "automation", "agents"])
def test_worker_task_modules_register_once(name):
    import importlib

    module = importlib.import_module(f"app.services.{name}.worker_tasks")
    tasks: list = []
    module.register(tasks)
    count = len(tasks)
    module.register(tasks)
    assert len(tasks) == count and count >= 1
