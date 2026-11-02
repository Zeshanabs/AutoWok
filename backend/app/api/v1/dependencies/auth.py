from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.db.session import get_db
from app.models import Session, User, WorkspaceMembership
from app.services.sessions import clear_session_cookie

settings = get_settings()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def get_current_session(
    request: Request,
    response: Response,
    db: DBSession = Depends(get_db),
) -> Session:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session = db.query(Session).filter(Session.token_hash == token_hash).first()
    now = datetime.now(timezone.utc)
    if (
        session is None
        or session.revoked_at is not None
        or _as_utc(session.expires_at) <= now
        or not session.user.is_active
    ):
        clear_session_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    session.last_used_at = now
    db.commit()
    return session


def get_current_user(current_session: Session = Depends(get_current_session)) -> User:
    return current_session.user


def authorize_workspace(
    workspace_id: UUID,
    current_user: User,
    db: DBSession,
    allowed_roles: set[str] | None = None,
) -> WorkspaceMembership:
    membership = (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == current_user.id,
        )
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    if (membership.role == "OWNER") != (
        membership.workspace.owner_id == current_user.id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    if allowed_roles is not None and membership.role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient workspace permissions.")
    return membership


def require_workspace_role(*roles: str) -> Callable[..., WorkspaceMembership]:
    allowed_roles = set(roles)

    def dependency(
        workspace_id: UUID,
        current_user: User = Depends(get_current_user),
        db: DBSession = Depends(get_db),
    ) -> WorkspaceMembership:
        return authorize_workspace(workspace_id, current_user, db, allowed_roles)

    return dependency


require_workspace_member = require_workspace_role("OWNER", "ADMIN", "MEMBER")
require_workspace_admin = require_workspace_role("OWNER", "ADMIN")
require_workspace_owner = require_workspace_role("OWNER")
get_current_workspace = require_workspace_member
