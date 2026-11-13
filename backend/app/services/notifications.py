"""In-app notifications (Phase 10).

A small reusable service: one row per recipient, workspace-scoped, with an
optional ``dedupe_key`` so retried automation steps never notify twice. Rows
are added to the caller's session; the caller commits.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from app.models import Notification, WorkspaceMembership

ADMIN_ROLES = ("OWNER", "ADMIN")
MAX_TITLE = 200
MAX_MESSAGE = 2000


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def workspace_member_ids(db: DBSession, workspace_id: UUID, *, roles: Iterable[str] | None = None) -> list[UUID]:
    query = db.query(WorkspaceMembership.user_id).filter(WorkspaceMembership.workspace_id == workspace_id)
    if roles is not None:
        query = query.filter(WorkspaceMembership.role.in_(tuple(roles)))
    return [row.user_id for row in query.order_by(WorkspaceMembership.joined_at).all()]


def is_member(db: DBSession, workspace_id: UUID, user_id: UUID) -> bool:
    return (
        db.query(WorkspaceMembership.id)
        .filter(WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.user_id == user_id)
        .first()
        is not None
    )


def notify(
    db: DBSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    category: str,
    title: str,
    message: str,
    resource_type: str | None = None,
    resource_id: UUID | str | None = None,
    automation_id: UUID | None = None,
    execution_id: UUID | None = None,
    dedupe_key: str | None = None,
) -> Notification | None:
    """Create a notification for a workspace member. Returns None if deduplicated or not a member."""
    if not is_member(db, workspace_id, user_id):
        return None
    if dedupe_key is not None:
        existing = db.query(Notification.id).filter(Notification.dedupe_key == dedupe_key).first()
        if existing is not None:
            return None
    notification = Notification(
        workspace_id=workspace_id,
        user_id=user_id,
        category=category[:40],
        title=title.strip()[:MAX_TITLE] or "Notification",
        message=message.strip()[:MAX_MESSAGE],
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        automation_id=automation_id,
        execution_id=execution_id,
        dedupe_key=dedupe_key,
    )
    db.add(notification)
    return notification


def notify_many(
    db: DBSession,
    user_ids: Iterable[UUID],
    *,
    workspace_id: UUID,
    dedupe_prefix: str | None = None,
    **kwargs,
) -> list[Notification]:
    created: list[Notification] = []
    for user_id in dict.fromkeys(user_ids):
        dedupe_key = f"{dedupe_prefix}:{user_id}" if dedupe_prefix else None
        notification = notify(db, workspace_id=workspace_id, user_id=user_id, dedupe_key=dedupe_key, **kwargs)
        if notification is not None:
            created.append(notification)
    return created


def notify_admins(db: DBSession, *, workspace_id: UUID, dedupe_prefix: str | None = None, **kwargs) -> list[Notification]:
    return notify_many(
        db, workspace_member_ids(db, workspace_id, roles=ADMIN_ROLES), workspace_id=workspace_id, dedupe_prefix=dedupe_prefix, **kwargs
    )


def unread_count(db: DBSession, *, workspace_id: UUID, user_id: UUID) -> int:
    return (
        db.query(Notification.id)
        .filter(Notification.workspace_id == workspace_id, Notification.user_id == user_id, Notification.read_at.is_(None))
        .count()
    )
