"""Workspace invitations by email.

An admin invites an email address. Autowok stores a hash of a random token and
emails a link containing the token. The invited person opens the link, signs in
(or registers) with that same email address and accepts.

Why both the token and the matching email are required: Autowok does not verify
email addresses at registration, so the email alone proves nothing, while the
token alone could be forwarded. Together they show that the person who controls
the invited mailbox is the one joining.
"""

from __future__ import annotations

import hashlib
import html
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import get_current_user, require_workspace_admin
from app.core.config import get_settings
from app.db.session import get_db
from app.models import User, Workspace, WorkspaceInvitation, WorkspaceMembership
from app.schemas.workspaces import (
    InvitationAccepted,
    InvitationCreate,
    InvitationCreated,
    InvitationPreview,
    InvitationRead,
    WorkspaceRole,
)
from app.services.audit import record_audit
from app.services.email import EmailError, email_configured, send_email
from app.services.identity import normalize_email
from app.services.rate_limit import enforce_user_rate_limit

router = APIRouter(tags=["invitations"])


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _state(invitation: WorkspaceInvitation) -> str:
    if invitation.accepted_at is not None:
        return "accepted"
    if invitation.revoked_at is not None:
        return "revoked"
    if _aware(invitation.expires_at) <= datetime.now(timezone.utc):
        return "expired"
    return "pending"


def _read(invitation: WorkspaceInvitation) -> InvitationRead:
    return InvitationRead(
        id=invitation.id,
        email=invitation.email,
        role=WorkspaceRole(invitation.role),
        status=_state(invitation),
        email_sent=invitation.email_sent_at is not None,
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
    )


def _invite_url(token: str) -> str:
    origins = get_settings().cors_origins_list
    base = (origins[0] if origins else "http://localhost:3000").rstrip("/")
    return f"{base}/invite/{token}"


def _send_invitation_email(*, to: str, workspace_name: str, inviter_name: str, role: str, url: str, days: int) -> None:
    role_text = "an admin" if role == WorkspaceRole.ADMIN.value else "a member"
    text = (
        f"{inviter_name} invited you to join the workspace \"{workspace_name}\" on Autowok as {role_text}.\n\n"
        f"Open this link to accept:\n{url}\n\n"
        f"Sign in or create an account with this email address ({to}) to join. "
        f"The link works for {days} days.\n\n"
        "If you were not expecting this invitation, you can ignore this email."
    )
    safe = {key: html.escape(value) for key, value in {"inviter": inviter_name, "workspace": workspace_name, "url": url, "to": to}.items()}
    body = (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.6;color:#141d20;max-width:520px">'
        f'<p><strong>{safe["inviter"]}</strong> invited you to join the workspace '
        f'<strong>{safe["workspace"]}</strong> on Autowok as {role_text}.</p>'
        f'<p><a href="{safe["url"]}" style="display:inline-block;background:#2347e0;color:#ffffff;'
        'padding:11px 20px;border-radius:8px;text-decoration:none;font-weight:bold">Accept invitation</a></p>'
        f'<p>Sign in or create an account with this email address ({safe["to"]}) to join. '
        f"The link works for {days} days.</p>"
        f'<p style="color:#627071;font-size:13px">If the button does not work, copy this address into your browser:<br>{safe["url"]}</p>'
        '<p style="color:#627071;font-size:13px">If you were not expecting this invitation, you can ignore this email.</p>'
        "</div>"
    )
    send_email(to=to, subject=f"{inviter_name} invited you to {workspace_name} on Autowok", text=text, html=body)


@router.post(
    "/workspaces/{workspace_id}/invitations",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_invitation(
    payload: InvitationCreate,
    workspace_access: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> InvitationCreated:
    settings = get_settings()
    if payload.role == WorkspaceRole.OWNER:
        raise HTTPException(status_code=400, detail="Ownership transfer is not supported.")
    # Each invitation sends an email to an address the caller chooses; keep it slow.
    enforce_user_rate_limit(
        current_user.id,
        action="member-add",
        limit=settings.rate_limit_member_add_per_hour,
        category="Member management",
    )
    email = normalize_email(str(payload.email))
    workspace = workspace_access.workspace
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user is not None and (
        db.query(WorkspaceMembership.id)
        .filter(WorkspaceMembership.workspace_id == workspace.id, WorkspaceMembership.user_id == existing_user.id)
        .first()
        is not None
    ):
        raise HTTPException(status_code=409, detail="User is already a workspace member.")

    now = datetime.now(timezone.utc)
    # A new invitation replaces any earlier open one for the same address, so
    # only the newest link works.
    for earlier in (
        db.query(WorkspaceInvitation)
        .filter(
            WorkspaceInvitation.workspace_id == workspace.id,
            WorkspaceInvitation.email == email,
            WorkspaceInvitation.accepted_at.is_(None),
            WorkspaceInvitation.revoked_at.is_(None),
        )
        .all()
    ):
        earlier.revoked_at = now

    token = secrets.token_urlsafe(32)
    invitation = WorkspaceInvitation(
        workspace_id=workspace.id,
        email=email,
        role=payload.role.value,
        token_hash=_hash_token(token),
        invited_by=current_user.id,
        expires_at=now + timedelta(days=settings.invitation_expiry_days),
    )
    db.add(invitation)
    record_audit(
        db,
        action="workspace.invitation_created",
        resource_type="invitation",
        actor_user_id=current_user.id,
        workspace_id=workspace.id,
        metadata={"role": payload.role.value},
    )
    db.commit()
    db.refresh(invitation)

    url = _invite_url(token)
    email_error: str | None = None
    if email_configured():
        try:
            _send_invitation_email(
                to=email,
                workspace_name=workspace.name,
                inviter_name=current_user.full_name,
                role=payload.role.value,
                url=url,
                days=settings.invitation_expiry_days,
            )
            invitation.email_sent_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(invitation)
        except EmailError as exc:
            email_error = str(exc)
    else:
        email_error = "Email sending is not set up on this server (SMTP settings are missing)."

    return InvitationCreated(**_read(invitation).model_dump(), invite_url=url, email_error=email_error)


@router.get("/workspaces/{workspace_id}/invitations", response_model=list[InvitationRead])
def list_invitations(
    workspace_access: WorkspaceMembership = Depends(require_workspace_admin),
    db: DBSession = Depends(get_db),
) -> list[InvitationRead]:
    rows = (
        db.query(WorkspaceInvitation)
        .filter(
            WorkspaceInvitation.workspace_id == workspace_access.workspace_id,
            WorkspaceInvitation.accepted_at.is_(None),
            WorkspaceInvitation.revoked_at.is_(None),
        )
        .order_by(WorkspaceInvitation.created_at.desc())
        .all()
    )
    return [_read(row) for row in rows]


@router.delete(
    "/workspaces/{workspace_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_invitation(
    workspace_id: UUID,
    invitation_id: UUID,
    workspace_access: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    invitation = (
        db.query(WorkspaceInvitation)
        .filter(
            WorkspaceInvitation.id == invitation_id,
            WorkspaceInvitation.workspace_id == workspace_access.workspace_id,
        )
        .first()
    )
    if invitation is None or invitation.accepted_at is not None:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    if invitation.revoked_at is None:
        invitation.revoked_at = datetime.now(timezone.utc)
        record_audit(
            db,
            action="workspace.invitation_revoked",
            resource_type="invitation",
            actor_user_id=current_user.id,
            workspace_id=workspace_access.workspace_id,
            resource_id=invitation.id,
        )
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _find_usable(db: DBSession, token: str) -> WorkspaceInvitation:
    invitation = (
        db.query(WorkspaceInvitation).filter(WorkspaceInvitation.token_hash == _hash_token(token)).first()
        if 20 <= len(token) <= 200
        else None
    )
    if invitation is None:
        raise HTTPException(status_code=404, detail="This invitation link is not valid.")
    state = _state(invitation)
    if state == "accepted":
        raise HTTPException(status_code=410, detail="This invitation has already been used.")
    if state == "revoked":
        raise HTTPException(status_code=410, detail="This invitation was cancelled. Ask for a new one.")
    if state == "expired":
        raise HTTPException(status_code=410, detail="This invitation has expired. Ask for a new one.")
    return invitation


@router.get("/invitations/{token}", response_model=InvitationPreview)
def preview_invitation(token: str, db: DBSession = Depends(get_db)) -> InvitationPreview:
    """What the link is for. Public: the token itself is the secret."""
    invitation = _find_usable(db, token)
    workspace = db.query(Workspace).filter(Workspace.id == invitation.workspace_id).first()
    return InvitationPreview(
        workspace_name=workspace.name if workspace else "",
        email=invitation.email,
        role=WorkspaceRole(invitation.role),
        expires_at=invitation.expires_at,
    )


@router.post("/invitations/{token}/accept", response_model=InvitationAccepted)
def accept_invitation(
    token: str,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> InvitationAccepted:
    invitation = _find_usable(db, token)
    if normalize_email(current_user.email) != invitation.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This invitation is for {invitation.email}. Sign in with that email address to accept it.",
        )
    already_member = (
        db.query(WorkspaceMembership.id)
        .filter(
            WorkspaceMembership.workspace_id == invitation.workspace_id,
            WorkspaceMembership.user_id == current_user.id,
        )
        .first()
        is not None
    )
    if not already_member:
        db.add(
            WorkspaceMembership(
                workspace_id=invitation.workspace_id,
                user_id=current_user.id,
                role=invitation.role,
            )
        )
    invitation.accepted_at = datetime.now(timezone.utc)
    record_audit(
        db,
        action="workspace.invitation_accepted",
        resource_type="invitation",
        actor_user_id=current_user.id,
        workspace_id=invitation.workspace_id,
        resource_id=invitation.id,
        metadata={"role": invitation.role},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="You are already a member of this workspace.") from exc
    return InvitationAccepted(workspace_id=invitation.workspace_id, role=WorkspaceRole(invitation.role))
