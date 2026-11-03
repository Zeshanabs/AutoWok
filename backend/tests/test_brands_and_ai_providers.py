from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from cryptography.fernet import Fernet
import pytest

from app.models import AIProviderConfig, AuditLog, Brand, TargetAudience
from app.schemas.brands import TargetAudienceUpdate
from app.services.ai_encryption import decrypt_api_key, rotate_api_key
from app.services.ai_providers import (
    ProviderTestResult,
    ProviderTestStatus,
    validate_provider_endpoint,
    validate_public_custom_endpoint,
)

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


def create_workspace(client) -> str:
    response = client.post(
        "/api/v1/workspaces",
        json={"name": "Brand workspace"},
        headers=CSRF,
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_brand_crud_context_role_checks_and_audit(client, client_factory, db_factory):
    register(client, "owner@example.com")
    workspace_id = create_workspace(client)
    created = client.post(
        f"/api/v1/workspaces/{workspace_id}/brands",
        json={"name": "Northwind Studio", "industry": "Design"},
        headers=CSRF,
    )
    assert created.status_code == 201
    brand = created.json()
    brand_id = brand["id"]

    voice = client.put(
        f"/api/v1/brands/{brand_id}/voice",
        json={
            "tone": "Warm",
            "language_preferences": ["en"],
            "prohibited_phrases": ["guaranteed results"],
        },
        headers=CSRF,
    )
    assert voice.status_code == 200
    assert client.get(f"/api/v1/brands/{brand_id}/voice").json()["tone"] == "Warm"
    audience = client.post(
        f"/api/v1/brands/{brand_id}/audiences",
        json={"audience_name": "Small design teams"},
        headers=CSRF,
    )
    assert audience.status_code == 201
    pillar = client.post(
        f"/api/v1/brands/{brand_id}/pillars",
        json={"name": "Design education"},
        headers=CSRF,
    )
    assert pillar.status_code == 201
    pillar_id = pillar.json()["id"]
    assert client.get(f"/api/v1/brands/{brand_id}/pillars/{pillar_id}").status_code == 200
    changed_pillar = client.patch(
        f"/api/v1/brands/{brand_id}/pillars/{pillar_id}",
        json={"priority": 2},
        headers=CSRF,
    )
    assert changed_pillar.status_code == 200
    assert changed_pillar.json()["priority"] == 2
    goal = client.post(
        f"/api/v1/brands/{brand_id}/goals",
        json={"goal_type": "brand_awareness", "title": "Increase recognition"},
        headers=CSRF,
    )
    assert goal.status_code == 201
    assert (
        client.get(
            f"/api/v1/brands/{brand_id}/goals/{goal.json()['id']}"
        ).status_code
        == 200
    )
    policy = client.post(
        f"/api/v1/brands/{brand_id}/policies",
        json={
            "policy_type": "prohibited_claim",
            "name": "No guarantees",
            "policy_value": "Do not guarantee specific outcomes.",
        },
        headers=CSRF,
    )
    assert policy.status_code == 201
    assert (
        client.get(
            f"/api/v1/brands/{brand_id}/policies/{policy.json()['id']}"
        ).status_code
        == 200
    )

    context = client.get(f"/api/v1/brands/{brand_id}/context")
    assert context.status_code == 200
    assert context.json()["brand"]["name"] == "Northwind Studio"
    assert context.json()["voice"]["tone"] == "Warm"
    assert context.json()["audiences"][0]["name"] == "Small design teams"
    assert context.json()["content_pillars"][0]["name"] == "Design education"
    assert context.json()["policies"][0]["name"] == "No guarantees"

    assert (
        client.patch(
            f"/api/v1/brands/{brand_id}/audiences/{audience.json()['id']}",
            json={"audience_name": None},
            headers=CSRF,
        ).status_code
        == 422
    )
    with client_factory() as member:
        register(member, "member@example.com")
        added = client.post(
            f"/api/v1/workspaces/{workspace_id}/members",
            json={"email": "member@example.com"},
            headers=CSRF,
        )
        assert added.status_code == 201
        assert member.get(f"/api/v1/brands/{brand_id}").status_code == 200
        assert member.get(f"/api/v1/brands/{brand_id}/context").status_code == 200
        assert (
            member.patch(
                f"/api/v1/brands/{brand_id}",
                json={"name": "Unauthorized"},
                headers=CSRF,
            ).status_code
            == 403
        )

    archived = client.delete(f"/api/v1/brands/{brand_id}", headers=CSRF)
    assert archived.status_code == 204
    assert client.get(f"/api/v1/brands/{brand_id}").status_code == 200
    assert client.get(f"/api/v1/brands/{brand_id}/context").status_code == 404
    with db_factory() as db:
        assert db.query(Brand).filter_by(id=UUID(brand_id)).one().status == "ARCHIVED"
        assert {log.action for log in db.query(AuditLog).all()} >= {
            "brand.created",
            "brand.voice_updated",
            "brand.archived",
        }


def test_target_audience_updates_reject_pii_keys():
    try:
        TargetAudienceUpdate.model_validate(
            {"demographics": {"interests": [{"email": "person@example.com"}]}}
        )
    except ValueError as exc:
        assert "personally identifying" in str(exc)
    else:
        raise AssertionError("Nested PII keys should be rejected.")


def test_provider_configuration_rejects_secret_like_keys():
    from app.schemas.brands import AIProviderCreate

    with pytest.raises(ValueError, match="Secrets must be provided"):
        AIProviderCreate.model_validate(
            {
                "provider_name": "openai",
                "display_name": "Primary",
                "model_name": "gpt-4o-mini",
                "api_key": "safe-test-key",
                "configuration": {"client_secret": "must-not-be-saved"},
            }
        )


def test_brand_routes_do_not_disclose_other_workspaces(client, client_factory):
    register(client, "owner@example.com")
    workspace_id = create_workspace(client)
    brand = client.post(
        f"/api/v1/workspaces/{workspace_id}/brands",
        json={"name": "Private brand"},
        headers=CSRF,
    )
    assert brand.status_code == 201

    with client_factory() as outsider:
        register(outsider, "outsider@example.com")
        brand_id = brand.json()["id"]
        assert outsider.get(f"/api/v1/brands/{brand_id}").status_code == 404
        assert (
            outsider.get(f"/api/v1/brands/{brand_id}/audiences").status_code
            == 404
        )
        assert (
            outsider.patch(
                f"/api/v1/brands/{brand_id}",
                json={"name": "Unauthorized"},
                headers=CSRF,
            ).status_code
            == 404
        )


def test_ai_provider_keys_are_encrypted_and_never_returned(
    client, client_factory, db_factory, monkeypatch
):
    key = Fernet.generate_key().decode("ascii")
    from app.services import ai_encryption

    monkeypatch.setattr(
        ai_encryption,
        "get_settings",
        lambda: SimpleNamespace(
            ai_encryption_key=key,
            ai_encryption_key_previous="",
        ),
    )
    register(client, "owner@example.com")
    workspace_id = create_workspace(client)
    api_key = "provider-secret-value"
    accidental_config_secret = "this-must-not-be-echoed"
    rejected = client.post(
        f"/api/v1/workspaces/{workspace_id}/ai-providers",
        json={
            "provider_name": "openai",
            "display_name": "Invalid provider",
            "model_name": "gpt-4o-mini",
            "api_key": api_key,
            "configuration": {"client_secret": accidental_config_secret},
        },
        headers=CSRF,
    )
    assert rejected.status_code == 422
    assert accidental_config_secret not in rejected.text
    assert api_key not in rejected.text
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/ai-providers",
        json={
            "provider_name": "openai",
            "display_name": "Primary OpenAI",
            "model_name": "gpt-4o-mini",
            "api_key": api_key,
            "is_default": True,
        },
        headers=CSRF,
    )
    assert response.status_code == 201
    provider_id = response.json()["id"]
    assert api_key not in response.text
    assert response.json()["api_key_configured"] is True
    assert response.json()["masked_api_key"] == "********"
    with db_factory() as db:
        provider = db.query(AIProviderConfig).one()
        assert provider.encrypted_api_key != api_key
        assert decrypt_api_key(provider.encrypted_api_key) == api_key
        assert provider.is_default is True

    from app.api.v1.routes import ai_providers

    monkeypatch.setattr(
        ai_providers,
        "_test_connection",
        lambda provider_name, api_key, base_url: ProviderTestResult(
            ProviderTestStatus.SUCCESS, "The provider connection succeeded."
        ),
    )
    tested = client.post(
        f"/api/v1/workspaces/{workspace_id}/ai-providers/{provider_id}/test",
        headers=CSRF,
    )
    assert tested.status_code == 200
    assert tested.json()["status"] == "success"
    assert api_key not in tested.text
    with db_factory() as db:
        provider = db.query(AIProviderConfig).one()
        assert provider.last_test_status == "success"
    replacement_key = "replacement-provider-secret"
    updated = client.patch(
        f"/api/v1/workspaces/{workspace_id}/ai-providers/{provider_id}",
        json={"api_key": replacement_key},
        headers=CSRF,
    )
    assert updated.status_code == 200
    assert replacement_key not in updated.text
    assert updated.json()["last_test_status"] is None
    with db_factory() as db:
        provider = db.query(AIProviderConfig).filter_by(id=UUID(provider_id)).one()
        assert decrypt_api_key(provider.encrypted_api_key) == replacement_key
        assert provider.last_tested_at is None

    with client_factory() as member:
        register(member, "member@example.com")
        assert client.post(
            f"/api/v1/workspaces/{workspace_id}/members",
            json={"email": "member@example.com"},
            headers=CSRF,
        ).status_code == 201
        assert member.get(
            f"/api/v1/workspaces/{workspace_id}/ai-providers"
        ).status_code == 200
        assert member.post(
            f"/api/v1/workspaces/{workspace_id}/ai-providers",
            json={
                "provider_name": "openai",
                "display_name": "Not allowed",
                "model_name": "gpt-4o-mini",
                "api_key": "another-secret",
            },
            headers=CSRF,
        ).status_code == 403

    second = client.post(
        f"/api/v1/workspaces/{workspace_id}/ai-providers",
        json={
            "provider_name": "anthropic",
            "display_name": "Secondary Claude",
            "model_name": "claude-3-5-sonnet",
            "api_key": "another-provider-secret",
            "is_default": True,
        },
        headers=CSRF,
    )
    assert second.status_code == 201
    with db_factory() as db:
        configs = {
            config.provider_name: config
            for config in db.query(AIProviderConfig).all()
        }
        assert sum(config.is_default for config in configs.values()) == 1
        assert configs["openai"].is_default is False
        assert configs["anthropic"].is_default is True
    disabled = client.patch(
        f"/api/v1/workspaces/{workspace_id}/ai-providers/{second.json()['id']}",
        json={"is_active": False},
        headers=CSRF,
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_default"] is False
    assert disabled.json()["is_active"] is False


def test_provider_encryption_fails_closed_without_a_key(client, monkeypatch):
    from app.services import ai_encryption

    monkeypatch.setattr(
        ai_encryption,
        "get_settings",
        lambda: SimpleNamespace(
            ai_encryption_key="",
            ai_encryption_key_previous="",
        ),
    )
    register(client, "owner@example.com")
    workspace_id = create_workspace(client)
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/ai-providers",
        json={
            "provider_name": "openai",
            "display_name": "Primary OpenAI",
            "model_name": "gpt-4o-mini",
            "api_key": "never-stored",
        },
        headers=CSRF,
    )
    assert response.status_code == 503


def test_fernet_rotation_reencrypts_with_primary_key(monkeypatch):
    from app.services import ai_encryption

    primary = Fernet.generate_key()
    previous = Fernet.generate_key()
    monkeypatch.setattr(
        ai_encryption,
        "get_settings",
        lambda: SimpleNamespace(
            ai_encryption_key=primary.decode("ascii"),
            ai_encryption_key_previous=previous.decode("ascii"),
        ),
    )
    old_token = Fernet(previous).encrypt(b"rotation-secret").decode("ascii")
    rotated = rotate_api_key(old_token)
    assert Fernet(primary).decrypt(rotated.encode("ascii")) == b"rotation-secret"


def test_previous_encryption_key_cannot_be_used_as_primary(monkeypatch):
    from app.services import ai_encryption
    from app.services.ai_encryption import EncryptionNotConfigured

    monkeypatch.setattr(
        ai_encryption,
        "get_settings",
        lambda: SimpleNamespace(
            ai_encryption_key="",
            ai_encryption_key_previous=Fernet.generate_key().decode("ascii"),
        ),
    )
    with pytest.raises(EncryptionNotConfigured, match="AI_ENCRYPTION_KEY"):
        ai_encryption.encrypt_api_key("secret")


def test_custom_provider_host_allowlist_and_public_dns(monkeypatch):
    from app.services import ai_providers

    monkeypatch.setattr(
        ai_providers,
        "get_settings",
        lambda: SimpleNamespace(
            ai_custom_endpoint_hosts_list=["api.example.com"],
        ),
    )
    endpoint = validate_provider_endpoint(
        "openai_compatible",
        "https://api.example.com/v1",
    )
    assert endpoint == "https://api.example.com/v1"
    with pytest.raises(ValueError, match="AI_CUSTOM_ENDPOINT_HOSTS"):
        validate_provider_endpoint(
            "openai_compatible",
            "https://other.example.com/v1",
        )
    with pytest.raises(ValueError, match="HTTPS"):
        validate_provider_endpoint(
            "openai_compatible",
            "http://api.example.com/v1",
        )

    monkeypatch.setattr(
        ai_providers.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("8.8.8.8", 443))],
    )
    addresses = validate_public_custom_endpoint(endpoint)
    assert addresses == ("8.8.8.8",)
    backend = ai_providers._PinnedNetworkBackend("api.example.com", addresses)
    connected_hosts = []
    monkeypatch.setattr(
        backend._backend,
        "connect_tcp",
        lambda host, *_args, **_kwargs: connected_hosts.append(host) or host,
    )
    assert backend.connect_tcp("api.example.com", 443) == "8.8.8.8"
    assert connected_hosts == ["8.8.8.8"]
    monkeypatch.setattr(
        ai_providers.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="non-public"):
        validate_public_custom_endpoint(endpoint)
