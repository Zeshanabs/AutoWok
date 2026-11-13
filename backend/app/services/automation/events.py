"""Event emission (outbox) and integration hooks.

``emit`` adds an ``AutomationEvent`` row to the caller's session so the event
is committed **together** with the business change it describes. The worker
later dispatches it. Emission never raises into business code: errors are
logged and the business operation continues.

Loop prevention: while an automation step runs, ``execution_scope`` records the
current execution. Any event emitted inside that scope is tagged with the
origin automation and ``chain_depth + 1``; the dispatcher refuses to match an
automation to events it caused itself and drops events beyond the maximum
chain depth.
"""

from __future__ import annotations

import contextlib
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import UUID, uuid4

from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.models import AutomationEvent, AutomationExecution, ContentApproval, ContentProject, ContentPublication
from app.models.analytics import AnalyticsSyncJob
from app.models.scheduling import ScheduledPost
from app.services.automation.registry import TriggerSpec, get_trigger, normalize_payload
from app.services.publishing import service as publishing

logger = logging.getLogger("autowok.automation")

_current_execution: ContextVar[AutomationExecution | None] = ContextVar("automation_execution", default=None)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@contextlib.contextmanager
def execution_scope(execution: AutomationExecution | None) -> Iterator[None]:
    token = _current_execution.set(execution)
    try:
        yield
    finally:
        _current_execution.reset(token)


def current_execution() -> AutomationExecution | None:
    return _current_execution.get()


def emit(
    db: DBSession,
    event_type: str,
    *,
    workspace_id: UUID,
    payload: dict[str, Any],
    source_entity_type: str | None = None,
    source_entity_id: UUID | str | None = None,
    dedupe_key: str | None = None,
    occurred_at: datetime | None = None,
) -> AutomationEvent | None:
    """Persist a trigger event in the caller's transaction. Returns None when skipped."""
    settings = get_settings()
    if not settings.automation_enabled:
        return None
    try:
        spec: TriggerSpec = get_trigger(event_type)
        normalized = normalize_payload(spec, payload)
        key = (dedupe_key or f"{event_type.lower()}:{uuid4().hex}")[:200]
        existing = db.query(AutomationEvent.id).filter(AutomationEvent.dedupe_key == key).first()
        if existing is not None:
            return None
        origin = current_execution()
        event = AutomationEvent(
            workspace_id=workspace_id,
            event_type=event_type,
            source_entity_type=source_entity_type or spec.entity_type,
            source_entity_id=str(source_entity_id) if source_entity_id is not None else None,
            event_payload=normalized,
            dedupe_key=key,
            status="pending",
            origin_automation_id=origin.automation_id if origin is not None else None,
            origin_execution_id=origin.id if origin is not None else None,
            chain_depth=(origin.chain_depth + 1) if origin is not None else 0,
            occurred_at=occurred_at or utc_now(),
        )
        db.add(event)
        db.flush()
        return event
    except Exception:  # noqa: BLE001 - automation must never break the business operation
        logger.exception("Could not record automation event %s", event_type)
        return None


# Content helpers ---------------------------------------------------------------


def content_payload(project: ContentProject, *, actor_user_id: UUID | None) -> dict[str, Any]:
    return {
        "project_id": project.id,
        "brand_id": project.brand_id,
        "title": project.title,
        "content_type": project.content_type,
        "platforms": list(project.selected_platforms or []),
        "status": project.status,
        "created_by": project.created_by,
        "assigned_to": project.assigned_to,
        "actor_user_id": actor_user_id,
        "labels": list(project.labels or []),
    }


def emit_content_created(db: DBSession, project: ContentProject, *, actor_user_id: UUID) -> None:
    emit(
        db,
        "CONTENT_CREATED",
        workspace_id=project.workspace_id,
        payload=content_payload(project, actor_user_id=actor_user_id),
        source_entity_id=project.id,
        dedupe_key=f"content_created:{project.id}",
    )


def emit_content_updated(db: DBSession, project: ContentProject, *, actor_user_id: UUID, change: str) -> None:
    emit(
        db,
        "CONTENT_UPDATED",
        workspace_id=project.workspace_id,
        payload={**content_payload(project, actor_user_id=actor_user_id)},
        source_entity_id=project.id,
        dedupe_key=f"content_updated:{project.id}:{change}:{uuid4().hex[:12]}",
    )


def emit_content_submitted(db: DBSession, project: ContentProject, approval: ContentApproval, *, actor_user_id: UUID) -> None:
    emit(
        db,
        "CONTENT_SUBMITTED_FOR_APPROVAL",
        workspace_id=project.workspace_id,
        payload={
            **content_payload(project, actor_user_id=actor_user_id),
            "approval_id": approval.id,
            "decision": "pending",
            "reviewer_id": None,
        },
        source_entity_id=project.id,
        dedupe_key=f"content_submitted:{approval.id}",
    )


def emit_content_decided(db: DBSession, project: ContentProject, approval: ContentApproval, *, reviewer_id: UUID) -> None:
    decision = approval.status
    event_type = "CONTENT_APPROVED" if decision == "approved" else "CONTENT_REJECTED"
    emit(
        db,
        event_type,
        workspace_id=project.workspace_id,
        payload={
            **content_payload(project, actor_user_id=reviewer_id),
            "approval_id": approval.id,
            "decision": decision,
            "reviewer_id": reviewer_id,
        },
        source_entity_id=project.id,
        dedupe_key=f"{event_type.lower()}:{approval.id}",
    )


def emit_team_member_assigned(db: DBSession, project: ContentProject, *, assigned_by: UUID | None) -> None:
    if project.assigned_to is None:
        return
    emit(
        db,
        "TEAM_MEMBER_ASSIGNED",
        workspace_id=project.workspace_id,
        payload={
            "project_id": project.id,
            "brand_id": project.brand_id,
            "title": project.title,
            "status": project.status,
            "assigned_to": project.assigned_to,
            "assigned_by": assigned_by,
            "created_by": project.created_by,
            "platforms": list(project.selected_platforms or []),
        },
        source_entity_id=project.id,
        dedupe_key=f"team_member_assigned:{project.id}:{project.assigned_to}:{uuid4().hex[:12]}",
    )


# Scheduling --------------------------------------------------------------------


def emit_post_scheduled(db: DBSession, post: ScheduledPost) -> None:
    project = db.get(ContentProject, post.project_id)
    emit(
        db,
        "POST_SCHEDULED",
        workspace_id=post.workspace_id,
        payload={
            "scheduled_post_id": post.id,
            "project_id": post.project_id,
            "draft_id": post.draft_id,
            "brand_id": post.brand_id,
            "platform": post.platform,
            "social_account_id": post.social_account_id,
            "scheduled_at": post.scheduled_at.isoformat() if post.scheduled_at else None,
            "timezone": post.timezone,
            "created_by": post.created_by,
            "title": project.title if project else None,
        },
        source_entity_id=post.id,
        dedupe_key=f"post_scheduled:{post.id}:{post.revision}",
    )


# Publishing hooks ----------------------------------------------------------------


def publication_payload(db: DBSession, job: ContentPublication) -> dict[str, Any]:
    project = db.get(ContentProject, job.project_id)
    schedule = db.query(ScheduledPost.id).filter(ScheduledPost.publication_id == job.id).first() if job.source == "schedule" else None
    return {
        "publication_id": job.id,
        "project_id": job.project_id,
        "draft_id": job.draft_id,
        "brand_id": project.brand_id if project else None,
        "platform": job.platform,
        "social_account_id": job.social_account_id,
        "source": job.source,
        "status": job.status,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "error_category": job.error_category,
        "error_code": job.error_code,
        "requires_user_action": job.requires_user_action,
        "outcome_uncertain": job.outcome_uncertain,
        "requested_by": job.requested_by,
        "scheduled_post_id": schedule.id if schedule else None,
        "title": project.title if project else None,
    }


def publication_completed(db: DBSession, job: ContentPublication) -> None:
    """Completion hook: emit POST_PUBLISHED / POST_PUBLISH_FAILED / POST_CANCELLED."""
    if job.status == "published":
        event_type, key = "POST_PUBLISHED", f"post_published:{job.id}"
    elif job.status == "failed":
        event_type, key = "POST_PUBLISH_FAILED", f"post_publish_failed:{job.id}:{job.attempt_count}"
    elif job.status == "cancelled":
        event_type, key = "POST_CANCELLED", f"post_cancelled:{job.id}"
    else:
        return
    emit(db, event_type, workspace_id=job.workspace_id, payload=publication_payload(db, job), source_entity_id=job.id, dedupe_key=key)


def publication_started(db: DBSession, job: ContentPublication) -> None:
    """Start hook: emit POST_PUBLISHING once per attempt."""
    emit(
        db,
        "POST_PUBLISHING",
        workspace_id=job.workspace_id,
        payload={**publication_payload(db, job), "status": "processing"},
        source_entity_id=job.id,
        dedupe_key=f"post_publishing:{job.id}:{job.attempt_count}",
    )


# Analytics ---------------------------------------------------------------------


def sync_payload(db: DBSession, job: AnalyticsSyncJob, *, consecutive_failures: int) -> dict[str, Any]:
    from app.models import SocialAccount

    account = db.get(SocialAccount, job.social_account_id)
    return {
        "sync_job_id": job.id,
        "social_account_id": job.social_account_id,
        "brand_id": account.brand_id if account else None,
        "platform": job.platform,
        "status": job.status,
        "trigger": job.trigger,
        "attempt_count": job.attempt_count,
        "consecutive_failures": consecutive_failures,
        "records_processed": job.records_processed,
        "error_category": job.error_category,
        "error_code": job.error_code,
        "requested_by": job.requested_by,
    }


def consecutive_sync_failures(db: DBSession, job: AnalyticsSyncJob) -> int:
    rows = (
        db.query(AnalyticsSyncJob.status)
        .filter(
            AnalyticsSyncJob.social_account_id == job.social_account_id,
            AnalyticsSyncJob.status.in_(("succeeded", "partial", "failed")),
        )
        .order_by(AnalyticsSyncJob.created_at.desc())
        .limit(20)
        .all()
    )
    count = 0
    for row in rows:
        if row.status == "failed":
            count += 1
        else:
            break
    return count


def emit_sync_finished(db: DBSession, job: AnalyticsSyncJob) -> None:
    if job.status in {"succeeded", "partial"}:
        event_type, failures = "ANALYTICS_SYNC_COMPLETED", 0
    elif job.status == "failed":
        event_type, failures = "ANALYTICS_SYNC_FAILED", max(1, consecutive_sync_failures(db, job))
    else:
        return
    emit(
        db,
        event_type,
        workspace_id=job.workspace_id,
        payload=sync_payload(db, job, consecutive_failures=failures),
        source_entity_id=job.id,
        dedupe_key=f"{event_type.lower()}:{job.id}",
    )


# Registration ------------------------------------------------------------------


def register_hooks() -> None:
    if publication_completed not in publishing.COMPLETION_HOOKS:
        publishing.COMPLETION_HOOKS.append(publication_completed)
    if publication_started not in publishing.START_HOOKS:
        publishing.START_HOOKS.append(publication_started)


register_hooks()
