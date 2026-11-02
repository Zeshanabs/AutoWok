from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import AuditLog, Session, User, Workspace, WorkspaceMembership

CSRF = {"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"}
PASSWORD = "StrongPassword#1234"


def register(client, email="user@example.com", password=PASSWORD):
    return client.post(
        "/api/v1/auth/register",
        json={"full_name": "Test User", "email": email, "password": password},
        headers=CSRF,
    )


def test_registration_creates_user_owner_workspace_and_hashed_session(
    client, db_factory
):
    response = register(client, "USER@Example.com")

    assert response.status_code == 201
    assert "password_hash" not in response.text
    assert "token_hash" not in response.text
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]

    with db_factory() as db:
        user = db.query(User).one()
        workspace = db.query(Workspace).one()
        membership = db.query(WorkspaceMembership).one()
        session = db.query(Session).one()
        actions = {entry.action for entry in db.query(AuditLog).all()}

        assert user.email == "user@example.com"
        assert user.password_hash != PASSWORD
        assert user.password_hash.startswith("$argon2id$")
        assert user.last_login_at is not None
        assert workspace.owner_id == user.id
        assert membership.role == "OWNER"
        assert membership.workspace_id == workspace.id
        assert session.token_hash != client.cookies.get("autowok_session")
        assert len(session.token_hash) == 64
        assert {"user.registered", "workspace.created"} <= actions


def test_duplicate_email_invalid_email_and_weak_password(client):
    assert register(client).status_code == 201
    duplicate = register(client, " USER@example.com ")
    invalid_email = register(client, "not-an-email")
    weak_password = register(client, "weak@example.com", "weak")

    assert duplicate.status_code == 409
    assert invalid_email.status_code == 422
    assert weak_password.status_code == 422


def test_login_current_user_logout_and_inactive_account(client, db_factory):
    assert register(client).status_code == 201
    client.post("/api/v1/auth/logout", headers=CSRF)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "USER@example.com", "password": PASSWORD},
        headers=CSRF,
    )
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "user@example.com"

    current = client.get("/api/v1/auth/me")
    assert current.status_code == 200
    assert current.json()["user"]["full_name"] == "Test User"
    assert current.json()["selected_workspace"] is None
    assert len(current.json()["workspaces"]) == 1
    selected_id = current.json()["workspaces"][0]["id"]
    selected = client.get(f"/api/v1/auth/me?workspace_id={selected_id}")
    assert selected.json()["selected_workspace"]["role"] == "OWNER"

    logout = client.post("/api/v1/auth/logout", headers=CSRF)
    assert logout.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401

    with db_factory() as db:
        user = db.query(User).one()
        user.is_active = False
        db.commit()
    inactive = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": PASSWORD},
        headers=CSRF,
    )
    assert inactive.status_code == 401
    assert inactive.json()["detail"] == "Invalid email or password."


def test_invalid_credentials_are_generic(client, db_factory):
    assert register(client).status_code == 201
    client.post("/api/v1/auth/logout", headers=CSRF)
    unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": PASSWORD},
        headers=CSRF,
    )
    wrong = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "WrongPassword#1234"},
        headers=CSRF,
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    with db_factory() as db:
        failed = db.query(AuditLog).filter(AuditLog.action == "auth.login_failed").all()
        assert len(failed) == 2
        assert all("password" not in str(item.details).lower() for item in failed)


def test_sessions_can_be_listed_revoked_and_logged_out_all(client, db_factory):
    registration = register(client)
    assert registration.status_code == 201
    client.post("/api/v1/auth/logout", headers=CSRF)
    assert client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": PASSWORD},
        headers=CSRF,
    ).status_code == 200

    sessions = client.get("/api/v1/auth/sessions")
    assert sessions.status_code == 200
    assert len(sessions.json()) == 1
    current_id = sessions.json()[0]["id"]
    assert sessions.json()[0]["is_current"] is True

    revoked = client.delete(f"/api/v1/auth/sessions/{current_id}", headers=CSRF)
    assert revoked.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401

    register(client, "other@example.com")
    client.post("/api/v1/auth/logout", headers=CSRF)
    client.post(
        "/api/v1/auth/login",
        json={"email": "other@example.com", "password": PASSWORD},
        headers=CSRF,
    )
    client.post(
        "/api/v1/auth/login",
        json={"email": "other@example.com", "password": PASSWORD},
        headers=CSRF,
    )
    logout_all = client.post("/api/v1/auth/logout-all", headers=CSRF)
    assert logout_all.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    with db_factory() as db:
        assert (
            db.query(Session)
            .filter(Session.user_id == db.query(User).filter_by(email="other@example.com").one().id)
            .filter(Session.revoked_at.is_(None))
            .count()
            == 0
        )


def test_expired_session_is_rejected(client, db_factory):
    assert register(client).status_code == 201
    with db_factory() as db:
        session = db.query(Session).one()
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_users_cannot_revoke_another_users_session(client, db_factory):
    assert register(client).status_code == 201
    client.post("/api/v1/auth/logout", headers=CSRF)
    assert register(client, "second@example.com").status_code == 201
    second_session = client.get("/api/v1/auth/sessions").json()[0]["id"]
    client.post("/api/v1/auth/logout", headers=CSRF)
    assert register(client, "third@example.com").status_code == 201

    response = client.delete(
        f"/api/v1/auth/sessions/{second_session}", headers=CSRF
    )
    assert response.status_code == 404


def test_cookie_mutations_require_allowed_origin_and_csrf_header(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Test User",
            "email": "csrf@example.com",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 403


def test_unauthenticated_workspace_requests_are_rejected(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/workspaces").status_code == 401
    assert client.get(
        "/api/v1/workspaces/00000000-0000-0000-0000-000000000001/members"
    ).status_code == 401
    assert client.post(
        "/api/v1/workspaces",
        json={"name": "Private"},
        headers=CSRF,
    ).status_code == 401


def test_login_rate_limit_and_redis_failure_are_explicit(client, monkeypatch):
    invalid_payload = {"email": "attempts@example.com", "password": PASSWORD}
    for _ in range(10):
        response = client.post(
            "/api/v1/auth/login",
            json=invalid_payload,
            headers=CSRF,
        )
        assert response.status_code == 401
    limited = client.post(
        "/api/v1/auth/login",
        json=invalid_payload,
        headers=CSRF,
    )
    assert limited.status_code == 429

    import redis
    from app.services import rate_limit

    class UnavailableRedis:
        def eval(self, *args):
            raise redis.ConnectionError("unavailable")

    monkeypatch.setattr(rate_limit, "redis_client", UnavailableRedis())
    unavailable = client.post(
        "/api/v1/auth/login",
        json={"email": "other@example.com", "password": PASSWORD},
        headers=CSRF,
    )
    assert unavailable.status_code == 503
    response = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Test User",
            "email": "csrf@example.com",
            "password": PASSWORD,
        },
        headers={"Origin": "https://attacker.example", "X-CSRF-Protection": "1"},
    )
    assert response.status_code == 403
