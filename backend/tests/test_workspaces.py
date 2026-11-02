from __future__ import annotations

from uuid import UUID

from app.models import AuditLog, User, WorkspaceMembership

CSRF = {"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"}
PASSWORD = "StrongPassword#1234"


def register(client, email):
    return client.post(
        "/api/v1/auth/register",
        json={"full_name": email.split("@")[0].title(), "email": email, "password": PASSWORD},
        headers=CSRF,
    )


def create_workspace(client, name="Team"):
    return client.post(
        "/api/v1/workspaces",
        json={"name": name},
        headers=CSRF,
    )


def test_default_workspace_and_workspace_crud(client):
    assert register(client, "owner@example.com").status_code == 201
    owned = client.get("/api/v1/workspaces")
    assert owned.status_code == 200
    assert len(owned.json()) == 1

    created = create_workspace(client, "Research Team")
    assert created.status_code == 201
    workspace = created.json()
    workspace_id = workspace["id"]
    assert workspace["name"] == "Research Team"
    assert client.get(f"/api/v1/workspaces/{workspace_id}").status_code == 200

    update = client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        json={"name": "Research Group"},
        headers=CSRF,
    )
    assert update.status_code == 200
    assert update.json()["name"] == "Research Group"
    assert len(client.get("/api/v1/workspaces").json()) == 2


def test_member_management_role_restrictions_and_audit(
    client, client_factory, db_factory
):
    assert register(client, "owner@example.com").status_code == 201
    workspace_id = create_workspace(client).json()["id"]
    with client_factory() as member_client:
        assert register(member_client, "member@example.com").status_code == 201

        member = client.post(
            f"/api/v1/workspaces/{workspace_id}/members",
            json={"email": "member@example.com"},
            headers=CSRF,
        )
        assert member.status_code == 201
        member_id = member.json()["user_id"]
        assert member.json()["role"] == "MEMBER"
        duplicate = client.post(
            f"/api/v1/workspaces/{workspace_id}/members",
            json={"email": "member@example.com"},
            headers=CSRF,
        )
        assert duplicate.status_code == 409
        assert len(client.get(f"/api/v1/workspaces/{workspace_id}/members").json()) == 2
        assert member_client.get(
            f"/api/v1/workspaces/{workspace_id}/members"
        ).status_code == 200
        assert member_client.post(
            f"/api/v1/workspaces/{workspace_id}/members",
            json={"email": "owner@example.com"},
            headers=CSRF,
        ).status_code == 403
        assert member_client.patch(
            f"/api/v1/workspaces/{workspace_id}",
            json={"name": "Member no"},
            headers=CSRF,
        ).status_code == 403

        changed = client.patch(
            f"/api/v1/workspaces/{workspace_id}/members/{member_id}/role",
            json={"role": "ADMIN"},
            headers=CSRF,
        )
        assert changed.status_code == 200

    with db_factory() as db:
        owner_id = db.query(User).filter_by(email="owner@example.com").one().id
        owner_membership = (
            db.query(WorkspaceMembership)
            .filter_by(workspace_id=UUID(workspace_id), user_id=owner_id)
            .one()
        )
        assert owner_membership.role == "OWNER"
        actions = {audit.action for audit in db.query(AuditLog).all()}
        assert {
            "workspace.member_added",
            "workspace.member_role_changed",
        } <= actions

    assert client.delete(
        f"/api/v1/workspaces/{workspace_id}/members/{owner_id}",
        headers=CSRF,
    ).status_code == 400
    assert client.patch(
        f"/api/v1/workspaces/{workspace_id}/members/{owner_id}/role",
        json={"role": "MEMBER"},
        headers=CSRF,
    ).status_code == 400
    assert client.patch(
        f"/api/v1/workspaces/{workspace_id}/members/{member_id}/role",
        json={"role": "OWNER"},
        headers=CSRF,
    ).status_code == 400
    assert client.delete(
        f"/api/v1/workspaces/{workspace_id}/members/{member_id}",
        headers=CSRF,
    ).status_code == 204
    assert client.get(f"/api/v1/workspaces/{workspace_id}/members").json()[0]["role"] == "OWNER"


def test_member_and_admin_cannot_manage_members_or_access_private_workspaces(
    client, client_factory
):
    assert register(client, "owner@example.com").status_code == 201
    workspace_id = create_workspace(client).json()["id"]
    with client_factory() as outsider:
        assert register(outsider, "outsider@example.com").status_code == 201
        outsider_workspace_id = outsider.get("/api/v1/workspaces").json()[0]["id"]

        assert outsider.get(f"/api/v1/workspaces/{workspace_id}").status_code == 404
        assert outsider.get(f"/api/v1/workspaces/{workspace_id}/members").status_code == 404
        assert outsider.patch(
            f"/api/v1/workspaces/{workspace_id}",
            json={"name": "No access"},
            headers=CSRF,
        ).status_code == 404
        assert outsider.get(
            f"/api/v1/workspaces/{outsider_workspace_id}"
        ).status_code == 200
        assert outsider.get("/api/v1/workspaces/not-a-uuid").status_code == 422

    with client_factory() as admin:
        assert register(admin, "admin@example.com").status_code == 201
        assert client.post(
            f"/api/v1/workspaces/{workspace_id}/members",
            json={"email": "admin@example.com", "role": "ADMIN"},
            headers=CSRF,
        ).status_code == 201

        assert admin.patch(
            f"/api/v1/workspaces/{workspace_id}",
            json={"name": "Admin update"},
            headers=CSRF,
        ).status_code == 200
        owner_id = client.get("/api/v1/auth/me").json()["user"]["id"]
        assert admin.delete(
            f"/api/v1/workspaces/{workspace_id}/members/{owner_id}",
            headers=CSRF,
        ).status_code == 400
        assert admin.patch(
            f"/api/v1/workspaces/{workspace_id}/members/{owner_id}/role",
            json={"role": "MEMBER"},
            headers=CSRF,
        ).status_code == 400
        assert admin.post(
            f"/api/v1/workspaces/{workspace_id}/members",
            json={"email": "outsider@example.com", "role": "OWNER"},
            headers=CSRF,
        ).status_code == 400
