"""Workspace invitations by email.

The mail server is replaced by a recorder, so these tests verify the invitation
rules and the content of the email. They do NOT verify delivery through a real
SMTP server.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.api.v1.routes import invitations as invitation_routes
from app.core.config import get_settings
from app.models import WorkspaceInvitation
from app.services import email as email_service
from tests.agent_helpers import register, setup_workspace
from tests.publishing_helpers import CSRF

API = "/api/v1"
INVITED = "mike@example.com"


@pytest.fixture
def outbox(monkeypatch):
    """Email switched on, with sent messages collected instead of delivered."""
    sent: list[dict] = []
    monkeypatch.setattr(invitation_routes, "email_configured", lambda: True)
    monkeypatch.setattr(invitation_routes, "send_email", lambda **message: sent.append(message))
    return sent


def invite(client, workspace_id: str, email: str = INVITED, role: str = "MEMBER"):
    return client.post(f"{API}/workspaces/{workspace_id}/invitations", json={"email": email, "role": role}, headers=CSRF)


def token_of(response) -> str:
    return response.json()["invite_url"].rsplit("/", 1)[1]


def test_invite_sends_email_and_the_invited_person_joins(client_factory, outbox):
    owner, workspace_id = setup_workspace(client_factory)
    created = invite(owner, workspace_id, "Mike@Example.com", "ADMIN")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["email"] == INVITED and body["role"] == "ADMIN" and body["status"] == "pending"
    assert body["email_sent"] is True and body["email_error"] is None
    token = token_of(created)

    assert len(outbox) == 1
    message = outbox[0]
    assert message["to"] == INVITED and "Agent workspace" in message["subject"]
    assert body["invite_url"] in message["text"] and body["invite_url"] in message["html"]
    assert "as an admin" in message["text"]

    # The link shows what it is for without signing in.
    guest = client_factory()
    preview = guest.get(f"{API}/invitations/{token}")
    assert preview.status_code == 200
    assert preview.json()["workspace_name"] == "Agent workspace" and preview.json()["email"] == INVITED
    assert guest.post(f"{API}/invitations/{token}/accept", headers=CSRF).status_code == 401

    # Registering with the invited address and opening the link joins the workspace.
    register(guest, INVITED)
    accepted = guest.post(f"{API}/invitations/{token}/accept", headers=CSRF)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"workspace_id": workspace_id, "role": "ADMIN"}
    members = owner.get(f"{API}/workspaces/{workspace_id}/members").json()
    assert {(member["email"], member["role"]) for member in members} == {("owner@example.com", "OWNER"), (INVITED, "ADMIN")}

    # A link works once, and the invitation leaves the pending list.
    assert guest.post(f"{API}/invitations/{token}/accept", headers=CSRF).status_code == 410
    assert guest.get(f"{API}/invitations/{token}").status_code == 410
    assert owner.get(f"{API}/workspaces/{workspace_id}/invitations").json() == []


def test_the_token_is_stored_only_as_a_hash(client_factory, db_factory, outbox):
    owner, workspace_id = setup_workspace(client_factory)
    token = token_of(invite(owner, workspace_id))
    with db_factory() as db:
        row = db.query(WorkspaceInvitation).one()
        assert row.token_hash != token and len(row.token_hash) == 64 and token not in str(row.__dict__)
    listed = owner.get(f"{API}/workspaces/{workspace_id}/invitations")
    assert listed.status_code == 200 and token not in listed.text and "invite_url" not in listed.text


def test_only_the_invited_email_can_accept(client_factory, outbox):
    owner, workspace_id = setup_workspace(client_factory)
    token = token_of(invite(owner, workspace_id))
    stranger = client_factory()
    register(stranger, "stranger@example.com")
    refused = stranger.post(f"{API}/invitations/{token}/accept", headers=CSRF)
    assert refused.status_code == 403 and INVITED in refused.json()["detail"]
    members = owner.get(f"{API}/workspaces/{workspace_id}/members").json()
    assert [member["email"] for member in members] == ["owner@example.com"]


def test_a_new_invitation_replaces_the_old_link_and_revoke_cancels(client_factory, outbox):
    owner, workspace_id = setup_workspace(client_factory)
    first = token_of(invite(owner, workspace_id))
    second_response = invite(owner, workspace_id)
    second = token_of(second_response)
    guest = client_factory()
    assert guest.get(f"{API}/invitations/{first}").status_code == 410
    assert guest.get(f"{API}/invitations/{second}").status_code == 200
    pending = owner.get(f"{API}/workspaces/{workspace_id}/invitations").json()
    assert [row["id"] for row in pending] == [second_response.json()["id"]]

    revoked = owner.delete(f"{API}/workspaces/{workspace_id}/invitations/{pending[0]['id']}", headers=CSRF)
    assert revoked.status_code == 204
    assert guest.get(f"{API}/invitations/{second}").status_code == 410
    assert owner.get(f"{API}/workspaces/{workspace_id}/invitations").json() == []


def test_expired_and_unknown_links_are_refused(client_factory, db_factory, outbox):
    owner, workspace_id = setup_workspace(client_factory)
    token = token_of(invite(owner, workspace_id))
    with db_factory() as db:
        row = db.query(WorkspaceInvitation).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    guest = client_factory()
    expired = guest.get(f"{API}/invitations/{token}")
    assert expired.status_code == 410 and "expired" in expired.json()["detail"]
    assert guest.get(f"{API}/invitations/{'x' * 43}").status_code == 404
    assert guest.get(f"{API}/invitations/short").status_code == 404


def test_only_admins_can_invite_and_existing_members_are_refused(client_factory, outbox):
    owner, workspace_id = setup_workspace(client_factory)
    member = client_factory()
    register(member, "member@example.com")
    assert owner.post(f"{API}/workspaces/{workspace_id}/members", json={"email": "member@example.com"}, headers=CSRF).status_code == 201

    assert invite(member, workspace_id).status_code == 403
    assert member.get(f"{API}/workspaces/{workspace_id}/invitations").status_code == 403
    assert invite(owner, workspace_id, "member@example.com").status_code == 409
    assert invite(owner, workspace_id, role="OWNER").status_code == 400
    outsider = client_factory()
    register(outsider, "outsider@example.com")
    assert invite(outsider, workspace_id).status_code in {403, 404}
    assert outbox == []


def test_without_smtp_the_link_is_returned_for_manual_sharing(client_factory, monkeypatch):
    monkeypatch.setattr(get_settings(), "smtp_host", "")
    owner, workspace_id = setup_workspace(client_factory)
    created = invite(owner, workspace_id)
    assert created.status_code == 201
    body = created.json()
    assert body["email_sent"] is False and "not set up" in body["email_error"]
    assert body["invite_url"].startswith("http://localhost:3000/invite/")


def test_a_mail_server_failure_keeps_the_invitation_and_hides_the_password(client_factory, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "Autowok <no-reply@example.com>")
    monkeypatch.setattr(settings, "smtp_username", "mailer")
    monkeypatch.setattr(settings, "smtp_password", "smtp-secret-password")

    class RefusingServer:
        def __init__(self, *args, **kwargs):
            raise OSError("connection refused")

    monkeypatch.setattr(email_service.smtplib, "SMTP", RefusingServer)
    owner, workspace_id = setup_workspace(client_factory)
    created = invite(owner, workspace_id)
    assert created.status_code == 201
    body = created.json()
    assert body["email_sent"] is False and "could not be reached" in body["email_error"]
    assert "smtp-secret-password" not in created.text and body["invite_url"]


def test_send_email_builds_a_safe_message(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "Autowok <no-reply@example.com>")
    monkeypatch.setattr(settings, "smtp_username", "mailer")
    monkeypatch.setattr(settings, "smtp_password", "smtp-secret-password")
    monkeypatch.setattr(settings, "smtp_security", "starttls")
    seen: dict = {}

    class FakeServer:
        def __init__(self, host, port, timeout=None):
            seen["address"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def starttls(self, context=None):
            seen["tls"] = True

        def login(self, username, password):
            seen["login"] = username

        def send_message(self, message):
            seen["message"] = message

    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeServer)
    email_service.send_email(to="mike@example.com", subject="Hello\r\nBcc: attacker@example.com", text="Plain", html="<p>Rich</p>")
    message = seen["message"]
    assert seen["address"] == ("smtp.example.com", 587) and seen["tls"] is True and seen["login"] == "mailer"
    assert message["To"] == "mike@example.com" and message["From"] == "Autowok <no-reply@example.com>"
    assert "\n" not in message["Subject"] and message["Bcc"] is None
    assert message.is_multipart()

    with pytest.raises(email_service.EmailError, match="not valid"):
        email_service.send_email(to="not-an-address", subject="x", text="y")
