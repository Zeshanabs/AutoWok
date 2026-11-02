from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import get_current_session, get_current_user
from app.db.session import get_db
from app.models import Session, User, Workspace, WorkspaceMembership
from app.schemas.auth import (
    CurrentSessionRead,
    CurrentUserResponse,
    LoginRequest,
    RegistrationResponse,
    RegisterRequest,
    SessionRead,
    UserRead,
    WorkspaceRead,
)
from app.services.audit import record_audit
from app.services.identity import generate_workspace_slug, normalize_email
from app.services.passwords import hash_password, password_hasher, verify_password
from app.services.rate_limit import enforce_rate_limit
from app.services.sessions import clear_session_cookie, new_session, set_session_cookie

router = APIRouter(prefix="/auth", tags=["authentication"])
_DUMMY_PASSWORD_HASH = password_hasher.hash("not-a-real-user-password")
logger = logging.getLogger("autowok.auth")


def _user_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        is_active=user.is_active,
        is_verified=user.is_verified,
    )


def _workspace_read(workspace: Workspace, role: str) -> WorkspaceRead:
    return WorkspaceRead(id=workspace.id, name=workspace.name, slug=workspace.slug, role=role)


@router.post("/register", response_model=RegistrationResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: DBSession = Depends(get_db),
) -> RegistrationResponse:
    email = normalize_email(str(payload.email))
    enforce_rate_limit(
        request, action="register", identity="address", limit=5, window_seconds=3600
    )
    if db.query(User.id).filter(User.email == email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.")

    stage = "creating account"
    try:
        user = User(
            full_name=payload.full_name,
            email=email,
            password_hash=hash_password(payload.password),
            is_active=True,
            is_verified=False,
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.flush()
        stage = "creating personal workspace"
        workspace_id = uuid4()
        workspace_name = f"{user.full_name}'s Workspace"[:100]
        workspace = Workspace(
            id=workspace_id,
            name=workspace_name,
            slug=generate_workspace_slug(workspace_name),
            owner_id=user.id,
        )
        db.add(workspace)
        membership = WorkspaceMembership(
            workspace=workspace,
            user=user,
            role="OWNER",
        )
        db.add(membership)
        db.flush()
        stage = "creating session and audit records"
        _, token = new_session(db, user, request.headers.get("user-agent"))
        record_audit(
            db,
            action="user.registered",
            resource_type="user",
            actor_user_id=user.id,
            resource_id=user.id,
        )
        record_audit(
            db,
            action="workspace.created",
            resource_type="workspace",
            actor_user_id=user.id,
            workspace_id=workspace.id,
            resource_id=workspace.id,
            metadata={"source": "registration"},
        )
        stage = "committing registration"
        db.commit()
        set_session_cookie(response, token)
        return RegistrationResponse(
            user=_user_read(user),
            workspace=_workspace_read(workspace, "OWNER"),
        )
    except IntegrityError as exc:
        db.rollback()
        existing_user = db.query(User.id).filter(User.email == email).first()
        if existing_user:
            detail = "An account with this email already exists."
        else:
            detail = "Registration could not be completed."
        original_error = exc.orig
        constraint = getattr(getattr(original_error, "diag", None), "constraint_name", None)
        sqlstate = getattr(original_error, "sqlstate", None)
        logger.warning(
            "Registration failed at %s (constraint=%s, sqlstate=%s, existing_email=%s)",
            stage,
            constraint,
            sqlstate,
            existing_user is not None,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        ) from exc
    except SQLAlchemyError:
        db.rollback()
        raise


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DBSession = Depends(get_db),
) -> dict[str, UserRead]:
    email = normalize_email(str(payload.email))
    enforce_rate_limit(
        request, action="login-ip", identity="address", limit=60, window_seconds=900
    )
    enforce_rate_limit(
        request, action="login", identity=email, limit=10, window_seconds=900
    )
    user = db.query(User).filter(User.email == email).first()
    password_hash = user.password_hash if user else _DUMMY_PASSWORD_HASH
    valid_password = verify_password(payload.password, password_hash)
    if user is None or not valid_password or not user.is_active:
        record_audit(
            db,
            action="auth.login_failed",
            resource_type="account",
            actor_user_id=user.id if user else None,
            metadata={"reason": "invalid_credentials"},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    now = datetime.now(timezone.utc)
    user.last_login_at = now
    _, token = new_session(db, user, request.headers.get("user-agent"))
    record_audit(
        db,
        action="auth.login",
        resource_type="user",
        actor_user_id=user.id,
        resource_id=user.id,
    )
    db.commit()
    set_session_cookie(response, token)
    return {"user": _user_read(user)}


@router.get("/me", response_model=CurrentUserResponse)
def current_user(
    workspace_id: UUID | None = None,
    current_session: Session = Depends(get_current_session),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> CurrentUserResponse:
    memberships = (
        db.query(WorkspaceMembership)
        .filter(WorkspaceMembership.user_id == current_user.id)
        .all()
    )
    workspaces = [
        _workspace_read(membership.workspace, membership.role)
        for membership in memberships
    ]
    selected = None
    if workspace_id is not None:
        selected_membership = next(
            (membership for membership in memberships if membership.workspace_id == workspace_id),
            None,
        )
        if selected_membership is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        selected = _workspace_read(selected_membership.workspace, selected_membership.role)

    return CurrentUserResponse(
        user=_user_read(current_user),
        session=CurrentSessionRead(
            id=current_session.id,
            created_at=current_session.created_at,
            expires_at=current_session.expires_at,
            last_used_at=current_session.last_used_at,
        ),
        workspaces=workspaces,
        selected_workspace=selected,
    )


@router.post("/logout")
def logout(
    response: Response,
    current_session: Session = Depends(get_current_session),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, bool]:
    current_session.revoked_at = datetime.now(timezone.utc)
    record_audit(
        db,
        action="auth.logout",
        resource_type="session",
        actor_user_id=current_user.id,
        resource_id=current_session.id,
    )
    db.commit()
    clear_session_cookie(response)
    return {"ok": True}


@router.post("/logout-all")
def logout_all(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, bool]:
    now = datetime.now(timezone.utc)
    db.query(Session).filter(
        Session.user_id == current_user.id,
        Session.revoked_at.is_(None),
    ).update({Session.revoked_at: now}, synchronize_session=False)
    record_audit(
        db,
        action="auth.logout_all",
        resource_type="user",
        actor_user_id=current_user.id,
        resource_id=current_user.id,
    )
    db.commit()
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/sessions", response_model=list[SessionRead])
def list_sessions(
    current_session: Session = Depends(get_current_session),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[SessionRead]:
    now = datetime.now(timezone.utc)
    sessions = (
        db.query(Session)
        .filter(
            Session.user_id == current_user.id,
            Session.revoked_at.is_(None),
            Session.expires_at > now,
        )
        .order_by(Session.created_at.desc())
        .all()
    )
    return [
        SessionRead(
            id=session.id,
            created_at=session.created_at,
            last_used_at=session.last_used_at,
            expires_at=session.expires_at,
            device_label=(
                "Mobile browser"
                if session.user_agent and any(
                    hint in session.user_agent.casefold()
                    for hint in ("mobile", "android", "iphone", "ipad")
                )
                else "Browser" if session.user_agent else "Unknown device"
            ),
            is_current=session.id == current_session.id,
        )
        for session in sessions
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    session = (
        db.query(Session)
        .filter(Session.id == session_id, Session.user_id == current_user.id)
        .first()
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    if session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        record_audit(
            db,
            action="auth.session_revoked",
            resource_type="session",
            actor_user_id=current_user.id,
            resource_id=session.id,
        )
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
