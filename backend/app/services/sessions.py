from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Response
from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.models import Session, User

settings = get_settings()


def new_session(db: DBSession, user: User, user_agent: str | None) -> tuple[Session, str]:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    session = Session(
        user_id=user.id,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expires_at=now + timedelta(days=settings.session_ttl_days),
        created_at=now,
        last_used_at=now,
        user_agent=user_agent[:512] if user_agent else None,
    )
    db.add(session)
    return session, token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.secure_cookies,
        samesite=settings.session_cookie_samesite,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite=settings.session_cookie_samesite,
    )
