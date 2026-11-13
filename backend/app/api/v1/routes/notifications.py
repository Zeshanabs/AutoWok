"""Notifications and internal tasks (Phase 10).

Notifications are personal: a member only ever sees their own, scoped to the
workspace in the path. Tasks are workspace-wide work items created by
automations; members can list them and mark them done.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import get_current_user, require_workspace_member
from app.db.session import get_db
from app.models import ContentProject, ContentTask, Notification, User, WorkspaceMembership
from app.schemas.automation import NotificationBulkRead, NotificationListRead, NotificationRead, TaskRead
from app.services import notifications as N

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["notifications"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/notifications", response_model=NotificationListRead)
def list_notifications(
    workspace_id: UUID,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    membership: WorkspaceMembership = Depends(require_workspace_member),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    query = db.query(Notification).filter(Notification.workspace_id == workspace_id, Notification.user_id == current_user.id)
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    rows = query.order_by(Notification.created_at.desc()).limit(limit).all()
    return {
        "items": [NotificationRead.model_validate(row) for row in rows],
        "unread_count": N.unread_count(db, workspace_id=workspace_id, user_id=current_user.id),
    }


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    workspace_id: UUID,
    notification_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Notification:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.workspace_id != workspace_id or notification.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Notification not found.")
    if notification.read_at is None:
        notification.read_at = _now()
        db.commit()
        db.refresh(notification)
    return notification


@router.post("/notifications/read-all", response_model=NotificationListRead)
def mark_notifications_read(
    workspace_id: UUID,
    payload: NotificationBulkRead | None = None,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    query = db.query(Notification).filter(
        Notification.workspace_id == workspace_id, Notification.user_id == current_user.id, Notification.read_at.is_(None)
    )
    if payload is not None and payload.notification_ids:
        query = query.filter(Notification.id.in_(payload.notification_ids))
    now = _now()
    for row in query.all():
        row.read_at = now
    db.commit()
    rows = (
        db.query(Notification)
        .filter(Notification.workspace_id == workspace_id, Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "items": [NotificationRead.model_validate(row) for row in rows],
        "unread_count": N.unread_count(db, workspace_id=workspace_id, user_id=current_user.id),
    }


# Tasks --------------------------------------------------------------------------


def _task_read(db: DBSession, task: ContentTask) -> TaskRead:
    project = db.get(ContentProject, task.project_id) if task.project_id else None
    assignee = db.get(User, task.assigned_to) if task.assigned_to else None
    return TaskRead(
        id=task.id,
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        project_title=project.title if project else None,
        publication_id=task.publication_id,
        kind=task.kind,
        title=task.title,
        description=task.description,
        severity=task.severity,
        status=task.status,
        assigned_to=task.assigned_to,
        assigned_to_name=assignee.full_name if assignee else None,
        due_at=task.due_at,
        completed_at=task.completed_at,
        automation_id=task.automation_id,
        execution_id=task.execution_id,
        created_at=task.created_at,
    )


@router.get("/tasks", response_model=list[TaskRead])
def list_tasks(
    workspace_id: UUID,
    status_filter: str | None = Query(default=None, alias="status", pattern="^(open|done)$"),
    kind: str | None = Query(default=None, pattern="^(task|followup|reminder|incident|analytics_followup)$"),
    mine: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    membership: WorkspaceMembership = Depends(require_workspace_member),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[TaskRead]:
    query = db.query(ContentTask).filter(ContentTask.workspace_id == workspace_id)
    if status_filter:
        query = query.filter(ContentTask.status == status_filter)
    if kind:
        query = query.filter(ContentTask.kind == kind)
    if mine:
        query = query.filter(ContentTask.assigned_to == current_user.id)
    rows = query.order_by(ContentTask.created_at.desc()).limit(limit).all()
    return [_task_read(db, row) for row in rows]


@router.post("/tasks/{task_id}/complete", response_model=TaskRead)
def complete_task(
    workspace_id: UUID,
    task_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> TaskRead:
    task = db.get(ContentTask, task_id)
    if task is None or task.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task.status != "done":
        task.status = "done"
        task.completed_at = _now()
        task.completed_by = current_user.id
        db.commit()
        db.refresh(task)
    return _task_read(db, task)


@router.post("/tasks/{task_id}/reopen", response_model=TaskRead)
def reopen_task(
    workspace_id: UUID,
    task_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> TaskRead:
    task = db.get(ContentTask, task_id)
    if task is None or task.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task.status != "open":
        task.status = "open"
        task.completed_at = None
        task.completed_by = None
        db.commit()
        db.refresh(task)
    return _task_read(db, task)
