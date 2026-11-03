from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet

from app.models import MetaAuthorization, OAuthState, SocialAccount
from app.services.groq import (
    GroqAuthenticationError,
    GroqNotConfiguredError,
    GroqRateLimitError,
    GroqRequestError,
    GroqService,
    GroqTimeoutError,
)
from app.services.token_encryption import decrypt_token, encrypt_token

CSRF = {"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"}
PASSWORD = "StrongPassword#1234"


def register(client, email: str) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": email.split("@")[0].title(),
            "email": email,
            "password": PASSWORD,
        },
        headers=CSRF,
    )
    assert response.status_code == 201


def create_workspace(client) -> UUID:
    response = client.post(
        "/api/v1/workspaces",
        json={"name": "Phase 3 workspace"},
        headers=CSRF,
    )
    assert response.status_code == 201
    return UUID(response.json()["id"])


def groq_settings(**changes):
    values = {
        "groq_enabled": True,
        "groq_api_key": "test-groq-key",
        "groq_api_base_url": "https://api.groq.com/openai/v1",
        "groq_default_model": "openai/gpt-oss-20b",
        "groq_timeout_seconds": 1,
        "groq_max_retries": 2,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def meta_settings(state_secret: str):
    return SimpleNamespace(
        meta_app_id="test-app-id",
        meta_app_secret="test-app-secret",
        meta_graph_api_version="v26.0",
        meta_redirect_uri="http://localhost:8000/api/v1/oauth/meta/callback",
        meta_oauth_state_secret=state_secret,
        meta_token_encryption_key="",
        meta_token_encryption_key_previous="",
        cors_origins_list=["http://localhost:3000"],
    )


def test_groq_requires_api_key_and_enabled_model():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as DBSession

    engine = create_engine("sqlite://")
    from app.db.session import Base
    from app.models import AIProviderConfig, Brand, User, Workspace, WorkspaceMembership  # noqa: F401

    Base.metadata.create_all(engine)
    try:
        with DBSession(engine) as db:
            missing_key = GroqService(
                db,
                uuid4(),
                settings=groq_settings(groq_api_key=""),
            )
            with pytest.raises(GroqNotConfiguredError, match="GROQ_API_KEY"):
                missing_key.list_models()
            missing_model = GroqService(
                db,
                uuid4(),
                settings=groq_settings(groq_default_model=""),
            )
            with pytest.raises(GroqNotConfiguredError, match="GROQ_DEFAULT_MODEL"):
                missing_model.test_connection()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_groq_model_list_retries_transient_get_without_leaking_key(db_factory):
    from uuid import uuid4

    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(
            200,
            json={"data": [{"id": "openai/gpt-oss-20b"}, {"id": "llama-model"}]},
        )

    delays = []
    with db_factory() as db:
        service = GroqService(
            db,
            uuid4(),
            settings=groq_settings(),
            transport=httpx.MockTransport(respond),
            sleep=delays.append,
            jitter=lambda *_: 0,
        )
        assert service.list_models() == ["llama-model", "openai/gpt-oss-20b"]
    assert len(calls) == 2
    assert calls[0].headers["Authorization"] == "Bearer test-groq-key"
    assert delays == [0.5]


def test_groq_rate_limit_is_not_retried_and_preserves_retry_after(db_factory):
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            429,
            headers={"Retry-After": "30"},
            json={"error": {"message": "limit"}},
        )

    with db_factory() as db:
        service = GroqService(
            db,
            uuid4(),
            settings=groq_settings(),
            transport=httpx.MockTransport(respond),
        )
        with pytest.raises(GroqRateLimitError) as error:
            service.list_models()
    assert error.value.retry_after == "30"
    assert len(calls) == 1


def test_groq_connection_test_handles_invalid_keys_and_models(db_factory):
    responses = [
        httpx.Response(401, json={"error": "unauthorized"}),
        httpx.Response(200, json={"data": [{"id": "different-model"}]}),
    ]

    def respond(_request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    with db_factory() as db:
        invalid_key = GroqService(
            db,
            uuid4(),
            settings=groq_settings(),
            transport=httpx.MockTransport(respond),
        )
        with pytest.raises(GroqAuthenticationError):
            invalid_key.test_connection()
        unsupported = GroqService(
            db,
            uuid4(),
            settings=groq_settings(),
            transport=httpx.MockTransport(respond),
        )
        with pytest.raises(GroqRequestError, match="not available"):
            unsupported.test_connection()


def test_groq_timeout_and_completion_usage(db_factory):
    with db_factory() as db:
        timeout = GroqService(
            db,
            uuid4(),
            settings=groq_settings(groq_max_retries=0),
            transport=httpx.MockTransport(
                lambda _request: (_ for _ in ()).throw(
                    httpx.ReadTimeout("timeout")
                )
            ),
        )
        with pytest.raises(GroqTimeoutError):
            timeout.list_models()

        captured: dict = {}

        def completion_response(request: httpx.Request) -> httpx.Response:
            captured["payload"] = __import__("json").loads(request.content)
            return httpx.Response(
                200,
                json={
                    "model": "openai/gpt-oss-20b",
                    "choices": [{"message": {"content": "Hello"}}],
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 2,
                        "total_tokens": 5,
                    },
                },
            )

        service = GroqService(
            db,
            uuid4(),
            settings=groq_settings(),
            transport=httpx.MockTransport(completion_response),
        )
        completion = service.generate_completion(
            "Say hello", max_tokens=8, temperature=0.2
        )
        assert completion.text == "Hello"
        assert completion.usage.total_tokens == 5
        assert service.get_usage_information() == completion.usage
        assert captured["payload"]["max_completion_tokens"] == 8
        assert captured["payload"]["model"] == "openai/gpt-oss-20b"
        with pytest.raises(GroqRequestError, match="characters"):
            service.generate_completion("x" * 32_001)


def test_meta_oauth_state_is_expiring_and_single_use(
    client, db_factory, monkeypatch
):
    from app.api.v1.routes import social_accounts

    secret = "test-state-secret"
    monkeypatch.setattr(
        social_accounts, "get_settings", lambda: meta_settings(secret)
    )
    register(client, "meta-owner@example.com")
    workspace_id = create_workspace(client)
    user_id = UUID(client.get("/api/v1/auth/me").json()["user"]["id"])

    active_state = "single-use-state"
    expired_state = "expired-state"
    with db_factory() as db:
        db.add_all(
            [
                OAuthState(
                    state_hash=social_accounts._state_digest(active_state),
                    provider="meta",
                    user_id=user_id,
                    workspace_id=workspace_id,
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                ),
                OAuthState(
                    state_hash=social_accounts._state_digest(expired_state),
                    provider="meta",
                    user_id=user_id,
                    workspace_id=workspace_id,
                    expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                ),
            ]
        )
        db.commit()
        user = db.get(__import__("app.models", fromlist=["User"]).User, user_id)
        assert social_accounts._consume_oauth_state(
            db, state=active_state, current_user=user
        ) is not None
        assert social_accounts._consume_oauth_state(
            db, state=active_state, current_user=user
        ) is None
        assert social_accounts._consume_oauth_state(
            db, state=expired_state, current_user=user
        ) is None


def test_meta_oauth_callback_exchanges_code_and_rejects_replay(
    client, db_factory, monkeypatch
):
    from app.api.v1.routes import social_accounts
    from app.models import User
    from app.services import meta_graph, token_encryption

    key = Fernet.generate_key().decode("ascii")
    settings = meta_settings("callback-state-secret")
    settings.meta_token_encryption_key = key
    monkeypatch.setattr(social_accounts, "get_settings", lambda: settings)
    monkeypatch.setattr(meta_graph, "get_settings", lambda: settings)
    monkeypatch.setattr(
        token_encryption,
        "get_settings",
        lambda: SimpleNamespace(
            meta_token_encryption_key=key,
            meta_token_encryption_key_previous="",
        ),
    )
    register(client, "callback-owner@example.com")
    workspace_id = create_workspace(client)
    user_id = UUID(client.get("/api/v1/auth/me").json()["user"]["id"])
    state = "callback-single-use-state"
    with db_factory() as db:
        db.add(
            OAuthState(
                state_hash=social_accounts._state_digest(state),
                provider="meta",
                user_id=user_id,
                workspace_id=workspace_id,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
        )
        db.commit()

    class FakeMetaGraph:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def exchange_code(self, code):
            assert code == "authorization-code"
            return "long-lived-user-token", 5_184_000

        def get_user(self, access_token):
            assert access_token == "long-lived-user-token"
            return {"id": "meta-user"}

        def get_permissions(self, access_token):
            assert access_token == "long-lived-user-token"
            return ["pages_show_list", "pages_read_engagement", "instagram_basic"]

    monkeypatch.setattr(social_accounts, "MetaGraphClient", FakeMetaGraph)
    response = client.get(
        f"/api/v1/oauth/meta/callback?state={state}&code=authorization-code",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "meta=connected" in response.headers["location"]

    with db_factory() as db:
        authorization = db.query(MetaAuthorization).one()
        assert authorization.workspace_id == workspace_id
        assert decrypt_token(authorization.encrypted_user_access_token) == (
            "long-lived-user-token"
        )
        assert db.get(User, user_id) is not None

    replay = client.get(
        f"/api/v1/oauth/meta/callback?state={state}&code=authorization-code",
        follow_redirects=False,
    )
    assert replay.status_code == 400


def test_meta_discovery_connects_page_and_professional_instagram_securely(
    client, db_factory, monkeypatch
):
    from app.api.v1.routes import social_accounts
    from app.services import meta_graph, token_encryption

    key = Fernet.generate_key().decode("ascii")
    state_secret = "oauth-state-secret"
    settings = meta_settings(state_secret)
    settings.meta_token_encryption_key = key
    monkeypatch.setattr(social_accounts, "get_settings", lambda: settings)
    monkeypatch.setattr(meta_graph, "get_settings", lambda: settings)
    monkeypatch.setattr(
        token_encryption,
        "get_settings",
        lambda: SimpleNamespace(
            meta_token_encryption_key=key,
            meta_token_encryption_key_previous="",
        ),
    )
    register(client, "social-owner@example.com")
    workspace_id = create_workspace(client)
    other_workspace_id = create_workspace(client)
    user_id = UUID(client.get("/api/v1/auth/me").json()["user"]["id"])
    brand_response = client.post(
        f"/api/v1/workspaces/{workspace_id}/brands",
        json={"name": "Autowok brand"},
        headers=CSRF,
    )
    other_brand_response = client.post(
        f"/api/v1/workspaces/{other_workspace_id}/brands",
        json={"name": "Other workspace brand"},
        headers=CSRF,
    )
    assert brand_response.status_code == other_brand_response.status_code == 201
    pages = [
        {
            "id": "page-123",
            "name": "Autowok Page",
            "username": "autowok",
            "category": "Software",
            "picture": {"data": {"url": "https://example.test/page.png"}},
            "tasks": ["MANAGE", "CREATE_CONTENT"],
            "access_token": "page-access-secret",
            "instagram_business_account": {
                "id": "instagram-123",
                "username": "autowok",
                "account_type": "BUSINESS",
                "profile_picture_url": "https://example.test/ig.png",
            },
        },
        {
            "id": "page-456",
            "name": "Personal Instagram Page",
            "tasks": ["MANAGE"],
            "access_token": "other-page-token",
            "instagram_business_account": {
                "id": "instagram-personal",
                "username": "personal",
                "account_type": "PERSONAL",
            },
        },
    ]

    class FakeMetaGraph:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def list_pages(self, access_token):
            assert access_token == "user-access-secret"
            return pages

        def get_social_account(self, *, account_id, platform, access_token):
            assert account_id == "page-123"
            assert platform == "facebook_page"
            assert access_token == "page-access-secret"
            return {"id": account_id, "name": "Autowok Page"}

    monkeypatch.setattr(social_accounts, "MetaGraphClient", FakeMetaGraph)
    with db_factory() as db:
        db.add(
            MetaAuthorization(
                workspace_id=workspace_id,
                authorized_by=user_id,
                meta_user_id="meta-user-1",
                encrypted_user_access_token=encrypt_token("user-access-secret"),
                granted_scopes=["pages_show_list", "pages_read_engagement", "instagram_basic"],
                access_token_expires_at=datetime.now(timezone.utc) + timedelta(days=50),
            )
        )
        db.commit()

    discovered_pages = client.get(
        f"/api/v1/workspaces/{workspace_id}/social-accounts/meta/facebook-pages"
    )
    assert discovered_pages.status_code == 200
    assert discovered_pages.json()[0]["platform_account_id"] == "page-123"
    assert "access_token" not in discovered_pages.text

    discovered_instagram = client.get(
        f"/api/v1/workspaces/{workspace_id}/social-accounts/meta/instagram-accounts"
    )
    assert discovered_instagram.status_code == 200
    assert [item["platform_account_id"] for item in discovered_instagram.json()] == [
        "instagram-123"
    ]

    invalid_brand = client.post(
        f"/api/v1/workspaces/{workspace_id}/social-accounts/meta/connect",
        json={
            "platform": "facebook_page",
            "platform_account_id": "page-123",
            "brand_id": other_brand_response.json()["id"],
        },
        headers=CSRF,
    )
    assert invalid_brand.status_code == 404

    page_response = client.post(
        f"/api/v1/workspaces/{workspace_id}/social-accounts/meta/connect",
        json={
            "platform": "facebook_page",
            "platform_account_id": "page-123",
            "brand_id": brand_response.json()["id"],
        },
        headers=CSRF,
    )
    assert page_response.status_code == 201
    assert page_response.json()["display_name"] == "Autowok Page"
    assert page_response.json()["brand_id"] == brand_response.json()["id"]
    assert "page-access-secret" not in page_response.text

    instagram_response = client.post(
        f"/api/v1/workspaces/{workspace_id}/social-accounts/meta/connect",
        json={
            "platform": "instagram",
            "platform_account_id": "instagram-123",
            "parent_page_id": "page-123",
        },
        headers=CSRF,
    )
    assert instagram_response.status_code == 201
    assert instagram_response.json()["parent_account_id"] == page_response.json()["id"]

    verified = client.post(
        f"/api/v1/workspaces/{workspace_id}/social-accounts/{page_response.json()['id']}/verify",
        headers=CSRF,
    )
    assert verified.status_code == 200
    assert verified.json()["connection_status"] == "connected"
    assert verified.json()["last_verified_at"] is not None

    with db_factory() as db:
        stored = (
            db.query(SocialAccount)
            .filter(SocialAccount.platform == "instagram")
            .one()
        )
        assert decrypt_token(stored.credential.encrypted_access_token) == "page-access-secret"
        assert "page-access-secret" not in stored.credential.encrypted_access_token
        count = db.query(SocialAccount).count()
        assert count == 2

    disconnected = client.post(
        f"/api/v1/workspaces/{workspace_id}/social-accounts/{page_response.json()['id']}/disconnect",
        headers=CSRF,
    )
    assert disconnected.status_code == 200
    assert disconnected.json()["connection_status"] == "disconnected"
    with db_factory() as db:
        page = db.query(SocialAccount).filter_by(platform_account_id="page-123").one()
        assert page.credential is None


def test_meta_authorize_fails_closed_without_credentials(client, monkeypatch):
    from app.api.v1.routes import social_accounts

    monkeypatch.setattr(
        social_accounts,
        "get_settings",
        lambda: SimpleNamespace(
            meta_app_id="",
            meta_app_secret="",
            meta_redirect_uri="",
            meta_oauth_state_secret="",
            cors_origins_list=["http://localhost:3000"],
        ),
    )
    register(client, "unconfigured-meta@example.com")
    workspace_id = create_workspace(client)

    response = client.get(
        f"/api/v1/oauth/meta/authorize?workspace_id={workspace_id}"
    )

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_meta_oauth_authorize_is_rate_limited_per_user_and_ip(client, monkeypatch):
    from app.api.v1.routes import social_accounts

    monkeypatch.setattr(
        social_accounts,
        "get_settings",
        lambda: meta_settings("rate-limit-state-secret"),
    )
    register(client, "rate-limited-meta@example.com")
    workspace_id = create_workspace(client)
    responses = [
        client.get(f"/api/v1/oauth/meta/authorize?workspace_id={workspace_id}")
        for _ in range(11)
    ]

    assert all(response.status_code == 503 for response in responses[:10])
    assert responses[10].status_code == 429
    assert responses[10].headers["Retry-After"] == "900"
