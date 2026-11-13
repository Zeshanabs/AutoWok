"""Approval reminder events.

The worker calls :func:`emit_due_approval_reminders` on every iteration. For
each approval request that is still pending it records at most one
``APPROVAL_REMINDER_DUE`` event per elapsed hour (dedupe key
``approval_reminder:<approval_id>:<hours>``), but only in workspaces that have
an enabled automation for that trigger, so idle workspaces generate nothing.
The dispatcher compares the automation's ``deadline_hours`` with the event's
``pending_hours`` and runs each automation at most once per approval request.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.models import Automation, ContentApproval, ContentProject
from app.services.automation.events import emit

logger = logging.getLogger("autowok.automation")
MAX_REMINDER_HOURS = 24 * 30


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def emit_due_approval_reminders(db: DBSession, *, now: datetime | None = None, limit: int = 200) -> int:
    if not get_settings().automation_enabled:
        return 0
    now = now or utc_now()
    workspace_ids = {
        row.workspace_id
        for row in db.query(Automation.workspace_id)
        .filter(Automation.trigger_type == "APPROVAL_REMINDER_DUE", Automation.status == "enabled")
        .distinct()
        .all()
    }
    if not workspace_ids:
        return 0
    rows = (
        db.query(ContentApproval, ContentProject)
        .join(ContentProject, ContentProject.id == ContentApproval.project_id)
        .filter(
            ContentApproval.status == "pending",
            ContentProject.workspace_id.in_(list(workspace_ids)),
            ContentApproval.created_at <= now - timedelta(hours=1),
        )
        .order_by(ContentApproval.created_at.asc())
        .limit(limit)
        .all()
    )
    emitted = 0
    for approval, project in rows:
        pending_hours = int((now - _utc(approval.created_at)).total_seconds() // 3600)
        if pending_hours < 1 or pending_hours > MAX_REMINDER_HOURS:
            continue
        event = emit(
            db,
            "APPROVAL_REMINDER_DUE",
            workspace_id=project.workspace_id,
            payload={
                "approval_id": approval.id,
                "project_id": project.id,
                "brand_id": project.brand_id,
                "title": project.title,
                "created_by": project.created_by,
                "assigned_to": project.assigned_to,
                "pending_hours": pending_hours,
                "submitted_at": _utc(approval.created_at).isoformat(),
                "platforms": list(project.selected_platforms or []),
            },
            source_entity_type="content_approval",
            source_entity_id=approval.id,
            dedupe_key=f"approval_reminder:{approval.id}:{pending_hours}",
            occurred_at=now,
        )
        if event is None:
            continue
        try:
            db.commit()
            emitted += 1
        except IntegrityError:
            # Another worker recorded the same reminder first.
            db.rollback()
    return emitted
