"""Phase 12 security verification.

Every test here uses in-memory fakes only (SQLite, FakeRedis, mocked Meta);
nothing is sent to a real service. Covers: production configuration checks,
secret redaction, security headers, request size limits, rate limits, content
deletion rules, export safety, SSRF protection and cross-workspace access.
"""

from __future__ import annotations

import logging
import socket
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet

from app.core import context
from app.core.config import Settings, get_settings
from app.core.logging import JsonFormatter, RedactionFilter, redact
from app.integrations.research.retrieval import fetcher
from app.services.analytics.reports import csv_safe
from app.services.rate_limit import enforce_user_rate_limit
from tests.publishing_helpers import (
    CSRF,
    FakeMeta,
    add_member,
    connect_account,
    create_approved_content,
    create_workspace,
    jpeg_bytes,
    register,
    run_job,
    upload,
)

FUTURE_LOCAL = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT10:00")
FB_OK = {("POST", "/page-1/feed"): {"id": "page-1_post"}, ("GET", "/page-1_post"): {"permalink_url": "https://facebook.com/p"}}


def production_env(**overrides: str) -> dict[str, str]:
    values = {
        "APP_ENV": "production",
        "APP_DEBUG": "false",
        "DATABASE_URL": "postgresql+psycopg://autowok:Zx9-long-random-value@db:5432/autowok",
        "CORS_ORIGINS": "https://app.example.com",
        "AI_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "MEDIA_URL_SIGNING_SECRET": "m" * 48,
        "METRICS_TOKEN": "t" * 32,
        "META_APP_ID": "",
    }
    values.update(overrides)
    return values


# Configuration ---------------------------------------------------------------------


def test_production_refuses_to_start_with_unsafe_configuration():
    with pytest.raises(ValueError) as error:
        Settings(_env_file=None, APP_ENV="production", APP_DEBUG="true", METRICS_TOKEN="")
    message = str(error.value)
    for name in ("APP_DEBUG", "DATABASE_URL", "CORS_ORIGINS", "AI_ENCRYPTION_KEY", "TOKEN_ENCRYPTION_KEY", "MEDIA_URL_SIGNING_SECRET", "METRICS_TOKEN"):
        assert name in message
    # Names only: the default database password must not be echoed.
    assert "autowok:autowok" not in message


def test_startup_error_names_settings_but_never_echoes_values(monkeypatch):
    from app.core import config

    load = config.get_settings.__wrapped__  # the uncached loader; the shared settings object is left alone
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://autowok:SuperSecretDbPassword@db:5432/autowok")
    monkeypatch.setenv("META_APP_ID", "123")
    monkeypatch.setenv("META_APP_SECRET", "meta-secret-value-should-not-appear")
    monkeypatch.setenv("META_OAUTH_STATE_SECRET", "")
    monkeypatch.setenv("METRICS_TOKEN", "")
    with pytest.raises(config.ConfigurationError) as error:
        load()
    message = str(error.value)
    assert "METRICS_TOKEN" in message and "META_OAUTH_STATE_SECRET" in message
    assert "SuperSecretDbPassword" not in message and "meta-secret-value" not in message
    assert error.value.__cause__ is None and error.value.__suppress_context__

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SESSION_TTL_DAYS", "9999")
    with pytest.raises(config.ConfigurationError) as field_error:
        load()
    assert "SESSION_TTL_DAYS" in str(field_error.value) and "SuperSecretDbPassword" not in str(field_error.value)


def test_production_accepts_complete_configuration_and_hardens_defaults():
    settings = Settings(_env_file=None, **production_env())
    assert settings.is_production and settings.secure_cookies
    assert settings.docs_enabled is False and settings.use_json_logs is True
    assert settings.production_problems() == []


def test_production_checks_meta_and_key_separation():
    shared = Fernet.generate_key().decode()
    with pytest.raises(ValueError) as error:
        Settings(
            _env_file=None,
            **production_env(AI_ENCRYPTION_KEY=shared, TOKEN_ENCRYPTION_KEY=shared, META_APP_ID="123", META_REDIRECT_URI="http://localhost/cb"),
        )
    message = str(error.value)
    assert "must be different keys" in message and "META_APP_SECRET" in message and "META_OAUTH_STATE_SECRET" in message


def test_development_configuration_still_starts_without_secrets():
    settings = Settings(_env_file=None)
    assert not settings.is_production and settings.docs_enabled


# Secrets in logs -------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, secret",
    [
        ("login failed password=Hunter2!secret", "Hunter2!secret"),
        ("Authorization: Bearer abcdefghijklmnop123456", "abcdefghijklmnop123456"),
        ("GET https://graph.facebook.com/oauth/access_token?client_secret=s3cr3tvalue&code=AQDxyz123", "s3cr3tvalue"),
        ("GET https://graph.facebook.com/oauth/access_token?client_secret=s3cr3tvalue&code=AQDxyz123", "AQDxyz123"),
        ('{"api_key": "gsk_abcdefghijklmnopqrstuvwxyz"}', "gsk_abcdefghijklmnopqrstuvwxyz"),
        ("connecting to postgresql+psycopg://autowok:dbpass99@db:5432/autowok", "dbpass99"),
        ("page token EAAGm0PX4ZCpsBAKZCabcdefghijklmnopqrstuvwxyz1234", "EAAGm0PX4ZCpsBAKZCabcdefghijklmnopqrstuvwxyz1234"),
    ],
)
def test_log_redaction_masks_credentials(text, secret):
    assert secret not in redact(text)


def test_log_redaction_keeps_counters_and_codes():
    assert redact("status_code=200 error_code=190 prompt_tokens=512") == "status_code=200 error_code=190 prompt_tokens=512"


def test_structured_log_line_has_context_and_no_secret():
    import json

    record = logging.LogRecord("autowok.test", logging.ERROR, __file__, 1, "token=%s failed", ("abc123secretvalue",), None)
    record.access_token = "EAAsecretsecretsecretsecretsecret"
    record.tokens_used = 42
    assert RedactionFilter().filter(record)
    with context.scope(request_id="req-12345678", correlation_id="cor-12345678", workspace_id="ws-1"):
        line = JsonFormatter("autowok-api", "test").format(record)
    payload = json.loads(line)
    assert payload["level"] == "ERROR" and payload["service"] == "autowok-api" and payload["environment"] == "test"
    assert payload["request_id"] == "req-12345678" and payload["correlation_id"] == "cor-12345678"
    assert payload["workspace_id"] == "ws-1" and payload["timestamp"].endswith("+00:00")
    assert payload["access_token"] == "[REDACTED]" and payload["tokens_used"] == 42
    assert "abc123secretvalue" not in line and "EAAsecret" not in line


# Headers, request ids, errors ------------------------------------------------------


def test_security_headers_and_request_id(client):
    response = client.get("/api/v1/health", headers={"X-Request-ID": "client-supplied-id-1"})
    assert response.headers["X-Request-ID"] == "client-supplied-id-1"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Cache-Control"] == "no-store"
    # A header value that is not a plain token is replaced, not echoed.
    injected = client.get("/api/v1/health", headers={"X-Request-ID": "bad id <script>"})
    assert injected.headers["X-Request-ID"] != "bad id <script>" and len(injected.headers["X-Request-ID"]) == 32


def test_health_does_not_disclose_environment_or_infrastructure(client):
    body = client.get("/api/v1/health").json()
    assert body == {"status": "ok", "service": "Autowok"}
    ready = client.get("/api/v1/ready").json()
    assert set(ready) == {"status", "service", "dependencies"} and set(ready["dependencies"]) == {"database", "redis"}


def test_unhandled_error_returns_generic_message_with_request_id(client_factory, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api.v1.routes import health
    from app.main import app

    def explode():
        raise RuntimeError("database password is hunter2-internal-detail")

    client_factory()  # installs the database override
    monkeypatch.setattr(health, "ping_redis", explode)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/api/v1/ready")
    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "An unexpected error occurred. Please try again."
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert "hunter2" not in response.text and "RuntimeError" not in response.text


def test_csrf_protection_requires_origin_and_header(client):
    payload = {"full_name": "Csrf Test", "email": "csrf@example.com", "password": "StrongPassword#1234"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 403
    assert client.post("/api/v1/auth/register", json=payload, headers={"Origin": "https://evil.example", "X-CSRF-Protection": "1"}).status_code == 403
    assert client.post("/api/v1/auth/register", json=payload, headers={"Origin": "http://localhost:3000"}).status_code == 403
    assert client.post("/api/v1/auth/register", json=payload, headers=CSRF).status_code == 201


# Sessions --------------------------------------------------------------------------


def test_invalid_expired_and_revoked_sessions_are_rejected(client, db_factory):
    from datetime import datetime, timedelta, timezone

    from app.models import Session

    register(client, "session@example.com")
    assert client.get("/api/v1/auth/me").status_code == 200
    cookie = get_settings().session_cookie_name
    token = client.cookies.get(cookie)

    forged = client.get("/api/v1/auth/me", cookies={cookie: "not-a-real-session-token"})
    assert forged.status_code == 401

    with db_factory() as db:
        session = db.query(Session).first()
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    client.cookies.set(cookie, token)
    assert client.get("/api/v1/auth/me").status_code == 401

    with db_factory() as db:
        session = db.query(Session).first()
        session.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        db.commit()
    client.cookies.set(cookie, token)
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout", headers=CSRF).status_code == 200
    client.cookies.set(cookie, token)
    assert client.get("/api/v1/auth/me").status_code == 401  # logout revoked it server-side


def test_session_activity_is_written_at_a_bounded_interval(client, db_factory, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.api.v1.dependencies import auth as auth_dependency
    from app.models import Session

    register(client, "touch@example.com")
    with db_factory() as db:
        first = db.query(Session).first().last_used_at
    client.get("/api/v1/auth/me")
    with db_factory() as db:
        assert db.query(Session).first().last_used_at == first  # within the interval: no write
        session = db.query(Session).first()
        session.last_used_at = datetime.now(timezone.utc) - timedelta(seconds=auth_dependency.settings.session_touch_interval_seconds + 5)
        db.commit()
        stale = session.last_used_at
    client.get("/api/v1/auth/me")
    with db_factory() as db:
        assert db.query(Session).first().last_used_at != stale


# Request size limits ---------------------------------------------------------------


def test_oversized_json_body_is_rejected_before_the_route(client):
    register(client, "big@example.com")
    huge = {"name": "x" * (get_settings().max_request_body_bytes + 10)}
    response = client.post("/api/v1/workspaces", json=huge, headers=CSRF)
    assert response.status_code == 413 and "too large" in response.json()["detail"]


def test_upload_without_a_session_is_refused_before_the_body_is_read(client_factory):
    anonymous = client_factory()
    response = upload(anonymous, str(uuid4()), jpeg_bytes(64, 64), "a.jpg")
    assert response.status_code == 401


def test_upload_limits_apply_to_content_length_and_file_type(client, monkeypatch):
    register(client, "upload@example.com")
    workspace_id = create_workspace(client)
    settings = get_settings()
    monkeypatch.setattr(settings, "media_max_image_bytes", 20_000)
    monkeypatch.setattr(settings, "media_max_video_bytes", 60_000)
    # Larger than every limit: rejected from the declared length.
    assert upload(client, workspace_id, b"\xff\xd8" + b"0" * (2 * 1024 * 1024), "big.jpg").status_code == 413
    # An image is held to the image limit even though videos may be larger.
    too_big_image = upload(client, workspace_id, b"\xff\xd8\xff" + b"0" * 30_000, "photo.jpg")
    assert too_big_image.status_code == 413 and "MB or smaller" in too_big_image.json()["detail"]
    # Disguised content is still rejected by content sniffing.
    assert upload(client, workspace_id, b"<html><script>alert(1)</script></html>", "page.jpg").status_code == 415
    assert upload(client, workspace_id, b"<svg xmlns='http://www.w3.org/2000/svg'/>", "x.svg").status_code in {415, 422}


def test_signed_media_url_rejects_malformed_signatures_without_an_error(client):
    response = client.get(f"/api/v1/public-media/{uuid4()}", params={"expires": 9999999999, "signature": "é" * 64})
    assert response.status_code == 422
    wrong = client.get(f"/api/v1/public-media/{uuid4()}", params={"expires": 9999999999, "signature": "a" * 64})
    assert wrong.status_code in {403, 404}


# Rate limits -----------------------------------------------------------------------


def test_user_rate_limit_is_independent_of_the_network_address(client_factory):
    client_factory()  # installs the fake Redis
    user = uuid4()
    for _ in range(3):
        enforce_user_rate_limit(user, action="unit", limit=3, category="Unit test")
    with pytest.raises(Exception) as error:
        enforce_user_rate_limit(user, action="unit", limit=3, category="Unit test")
    assert error.value.status_code == 429 and error.value.headers["Retry-After"] == "3600"
    assert "unit test" in error.value.detail.lower()
    enforce_user_rate_limit(uuid4(), action="unit", limit=3, category="Unit test")  # another user is unaffected


def test_login_has_an_account_wide_limit(client, monkeypatch):
    from app.api.v1.routes import auth

    register(client, "limited@example.com")
    monkeypatch.setattr(auth.settings, "rate_limit_login_per_account_15m", 3)
    statuses = [
        client.post("/api/v1/auth/login", json={"email": "limited@example.com", "password": "WrongPassword#1234"}, headers=CSRF).status_code
        for _ in range(4)
    ]
    assert statuses == [401, 401, 401, 429]


def test_workspace_creation_and_ai_generation_are_limited(client, monkeypatch):
    from app.api.v1.routes import content, workspaces

    register(client, "limits@example.com")
    monkeypatch.setattr(workspaces.settings, "max_workspaces_per_user", 2)  # the personal workspace counts
    assert client.post("/api/v1/workspaces", json={"name": "Second"}, headers=CSRF).status_code == 201
    capped = client.post("/api/v1/workspaces", json={"name": "Third"}, headers=CSRF)
    assert capped.status_code == 409 and "at most 2" in capped.json()["detail"]

    workspace_id = client.get("/api/v1/workspaces").json()[0]["id"]
    project = client.post("/api/v1/content/projects", json={"workspace_id": workspace_id, "title": "Post", "selected_platforms": ["facebook"]}, headers=CSRF).json()
    monkeypatch.setattr(content.settings, "rate_limit_ai_generate_per_hour", 1)
    first = client.post(f"/api/v1/content/projects/{project['id']}/generate", headers=CSRF)
    assert first.status_code != 429
    second = client.post(f"/api/v1/content/projects/{project['id']}/generate", headers=CSRF)
    assert second.status_code == 429 and second.headers["Retry-After"] == "3600"


def test_ai_tools_reject_malformed_workspace_ids(client):
    register(client, "tools@example.com")
    response = client.post("/api/v1/content/intelligence/ideas", json={"topic": "Coffee", "workspace_id": "not-a-uuid"}, headers=CSRF)
    assert response.status_code == 422


def test_client_error_reports_are_accepted_bounded_and_limited(client, monkeypatch):
    from app.api.v1.routes import client_errors

    ok = client.post("/api/v1/client-errors", json={"message": "Boom", "source": "window-error", "stack": "at x"}, headers=CSRF)
    assert ok.status_code == 204
    assert client.post("/api/v1/client-errors", json={"message": "x" * 600, "source": "window-error"}, headers=CSRF).status_code == 422
    assert client.post("/api/v1/client-errors", json={"message": "Boom", "source": "other"}, headers=CSRF).status_code == 422
    monkeypatch.setattr(client_errors.settings, "rate_limit_client_errors_per_hour", 1)
    assert client.post("/api/v1/client-errors", json={"message": "Again", "source": "window-error"}, headers=CSRF).status_code == 429


# Content deletion ------------------------------------------------------------------


def test_content_deletion_rules(client, client_factory, db_factory, token_key):
    from app.models import AuditLog

    register(client, "owner-del@example.com")
    workspace_id = create_workspace(client)
    member = client_factory()
    register(member, "member-del@example.com")
    add_member(client, workspace_id, "member-del@example.com")

    def new_project(as_client, title):
        return as_client.post("/api/v1/content/projects", json={"workspace_id": workspace_id, "title": title, "selected_platforms": ["facebook"]}, headers=CSRF).json()["id"]

    owners_draft = new_project(client, "Owner draft")
    members_draft = new_project(member, "Member draft")
    # A member cannot delete someone else's content...
    assert member.delete(f"/api/v1/content/projects/{owners_draft}", headers=CSRF).status_code == 403
    # ...but can delete their own draft; the deletion is audited.
    assert member.delete(f"/api/v1/content/projects/{members_draft}", headers=CSRF).status_code == 204
    with db_factory() as db:
        assert db.query(AuditLog).filter(AuditLog.action == "content.project_deleted").count() == 1

    # Published content cannot be deleted by anyone: the publishing record is kept.
    content = create_approved_content(client, workspace_id, platforms=("facebook",))
    account = connect_account(db_factory, workspace_id)
    job = client.post(f"/api/v1/content/drafts/{content['drafts']['facebook']}/publish", json={"social_account_id": account, "confirm": True}, headers=CSRF)
    assert job.status_code == 202, job.text
    queued = client.delete(f"/api/v1/content/projects/{content['project_id']}", headers=CSRF)
    assert queued.status_code == 409  # a publishing job is in progress
    assert run_job(db_factory, job.json()["id"], FakeMeta(dict(FB_OK))) == "published"
    published = client.delete(f"/api/v1/content/projects/{content['project_id']}", headers=CSRF)
    assert published.status_code == 409 and "kept as a record" in published.json()["detail"]
    assert client.get(f"/api/v1/publishing/jobs/{job.json()['id']}").status_code == 200
    # The owner can delete an unpublished project.
    assert client.delete(f"/api/v1/content/projects/{owners_draft}", headers=CSRF).status_code == 204


def test_content_list_is_paginated_with_a_total(client):
    register(client, "pages@example.com")
    workspace_id = create_workspace(client)
    for index in range(5):
        client.post("/api/v1/content/projects", json={"workspace_id": workspace_id, "title": f"Post {index}", "selected_platforms": ["facebook"]}, headers=CSRF)
    first = client.get("/api/v1/content/projects", params={"workspace_id": workspace_id, "limit": 2})
    assert first.headers["X-Total-Count"] == "5" and len(first.json()) == 2
    rest = client.get("/api/v1/content/projects", params={"workspace_id": workspace_id, "limit": 500, "offset": 2}).json()
    assert len(rest) == 3 and {item["id"] for item in rest}.isdisjoint({item["id"] for item in first.json()})
    assert client.get("/api/v1/content/projects", params={"workspace_id": workspace_id, "limit": 501}).status_code == 422


# Export safety ---------------------------------------------------------------------


def test_csv_cells_cannot_run_as_formulas():
    assert csv_safe('=HYPERLINK("https://evil.example","x")') == "'=HYPERLINK(\"https://evil.example\",\"x\")"
    assert csv_safe("+cmd|' /C calc'!A0") == "'+cmd|' /C calc'!A0"
    assert csv_safe("@SUM(A1)") == "'@SUM(A1)"
    assert csv_safe("-12.5") == "-12.5" and csv_safe("+3%") == "+3%"  # numbers stay numbers
    assert csv_safe("Plain caption") == "Plain caption" and csv_safe(42) == 42


# SSRF ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://127.0.0.1:8000/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "https://user:pass@example.com/",
        "https://example.com:8443/",
        "ftp://example.com/file",
        "file:///etc/passwd",
        "https://internal.local/",
    ],
)
def test_fetcher_refuses_unsafe_urls(url):
    assert fetcher.validate_url(url) is False
    with pytest.raises(ValueError):
        fetcher.fetch_page(url)


def test_fetcher_refuses_hosts_that_resolve_to_private_addresses(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 443))])
    with pytest.raises(fetcher.UnsafeUrlError):
        fetcher.fetch_page("https://rebind.example.com/page")


def test_fetcher_validates_every_redirect_and_limits_size(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    seen: list[str] = []

    def redirecting(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    with pytest.raises(ValueError):
        fetcher.fetch_page("https://public.example.com/start", transport=httpx.MockTransport(redirecting))
    assert len(seen) == 1 and "93.184.216.34" in seen[0]  # pinned to the checked address; the redirect was not followed

    big = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "text/html"}, content=b"a" * (fetcher.MAX_BYTES + 1)))
    with pytest.raises(RuntimeError):
        fetcher.fetch_page("https://public.example.com/big", transport=big)

    ok = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=b"<p>Hello</p>"))
    assert fetcher.fetch_page("https://public.example.com/ok", transport=ok) == "<p>Hello</p>"


# Cross-workspace access ------------------------------------------------------------


def test_another_workspace_cannot_read_or_change_anything(client, client_factory, db_factory, token_key):
    register(client, "tenant-a@example.com")
    workspace_id = create_workspace(client)
    content = create_approved_content(client, workspace_id, platforms=("facebook",))
    account = connect_account(db_factory, workspace_id)
    asset = upload(client, workspace_id, jpeg_bytes(200, 200), "a.jpg").json()
    job = client.post(f"/api/v1/content/drafts/{content['drafts']['facebook']}/publish", json={"social_account_id": account, "confirm": True}, headers=CSRF).json()

    outsider = client_factory()
    register(outsider, "tenant-b@example.com")
    project_id, draft_id = content["project_id"], content["drafts"]["facebook"]
    reads = [
        f"/api/v1/workspaces/{workspace_id}",
        f"/api/v1/workspaces/{workspace_id}/members",
        f"/api/v1/workspaces/{workspace_id}/brands",
        f"/api/v1/content/projects?workspace_id={workspace_id}",
        f"/api/v1/content/projects/{project_id}",
        f"/api/v1/content/projects/{project_id}/drafts",
        f"/api/v1/media-assets?workspace_id={workspace_id}",
        f"/api/v1/media-assets/{asset['id']}",
        f"/api/v1/media-assets/{asset['id']}/content",
        f"/api/v1/workspaces/{workspace_id}/publishing/jobs",
        f"/api/v1/publishing/jobs/{job['id']}",
        f"/api/v1/workspaces/{workspace_id}/publishing/queue",
        f"/api/v1/workspaces/{workspace_id}/calendar",
        f"/api/v1/workspaces/{workspace_id}/scheduled-posts",
        f"/api/v1/workspaces/{workspace_id}/social-accounts",
        f"/api/v1/workspaces/{workspace_id}/analytics/overview",
        f"/api/v1/workspaces/{workspace_id}/analytics/reports/export?format=csv",
        f"/api/v1/workspaces/{workspace_id}/automations",
        f"/api/v1/workspaces/{workspace_id}/notifications",
        f"/api/v1/workspaces/{workspace_id}/agent-workflows",
        f"/api/v1/workspaces/{workspace_id}/ai-providers",
    ]
    for path in reads:
        assert outsider.get(path).status_code == 404, path
    writes = [
        ("post", f"/api/v1/content/drafts/{draft_id}/publish", {"social_account_id": account, "confirm": True}),
        ("delete", f"/api/v1/content/projects/{project_id}", None),
        ("post", f"/api/v1/publishing/jobs/{job['id']}/cancel", {}),
        ("post", f"/api/v1/workspaces/{workspace_id}/scheduled-posts", {"draft_id": draft_id, "social_account_id": account, "scheduled_local": FUTURE_LOCAL, "timezone": "UTC", "confirm": True}),
        ("post", f"/api/v1/workspaces/{workspace_id}/analytics/sync", {}),
        ("post", f"/api/v1/workspaces/{workspace_id}/members", {"email": "tenant-b@example.com"}),
    ]
    for method, path, body in writes:
        response = getattr(outsider, method)(path, headers=CSRF, **({"json": body} if body is not None else {}))
        assert response.status_code == 404, (path, response.status_code)


def test_members_cannot_publish_approve_or_schedule(client, client_factory, db_factory, token_key):
    register(client, "boss@example.com")
    workspace_id = create_workspace(client)
    member = client_factory()
    register(member, "staff@example.com")
    add_member(client, workspace_id, "staff@example.com")
    content = create_approved_content(client, workspace_id, platforms=("facebook",), approve=False)
    account = connect_account(db_factory, workspace_id)
    draft_id, project_id = content["drafts"]["facebook"], content["project_id"]

    submitted = member.post(f"/api/v1/content/projects/{project_id}/submit-for-approval", json={}, headers=CSRF)
    assert submitted.status_code == 200
    # A member cannot approve (not even their own submission), publish or schedule.
    decision = member.post(f"/api/v1/content/projects/{project_id}/approvals/{submitted.json()['id']}/decision", json={"status": "approved"}, headers=CSRF)
    assert decision.status_code == 403
    assert member.post(f"/api/v1/content/drafts/{draft_id}/publish", json={"social_account_id": account, "confirm": True}, headers=CSRF).status_code == 403
    scheduled = member.post(
        f"/api/v1/workspaces/{workspace_id}/scheduled-posts",
        json={"draft_id": draft_id, "social_account_id": account, "scheduled_local": FUTURE_LOCAL, "timezone": "UTC", "confirm": True},
        headers=CSRF,
    )
    assert scheduled.status_code == 403
    # Unapproved content cannot be published even by the owner.
    blocked = client.post(f"/api/v1/content/drafts/{draft_id}/publish", json={"social_account_id": account, "confirm": True}, headers=CSRF)
    assert blocked.status_code in {400, 409, 422}
