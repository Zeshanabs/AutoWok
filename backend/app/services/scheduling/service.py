"""Scheduling lifecycle on top of the Phase 7 publishing jobs.

    scheduled ──due (scheduler claims revision)──▶ queued ──worker──▶ processing ──▶ published
        │                                            │                     └──────▶ failed
        └── cancel / reschedule (before due) ─▶ cancelled / scheduled (revision+1)

* The scheduler claims a due post with a conditional UPDATE on
  ``(id, status='scheduled', revision)`` and creates the publishing job in the
  **same transaction**, so a crash leaves either nothing or both.
* The job's idempotency key is ``schedule:<id>:<revision>``, so even a
  duplicate scheduler run cannot create a second job for the same revision.
* Cancel/reschedule of a queued post cancels its job with a conditional
  UPDATE that only succeeds while the job is still ``pending`` (not claimed by
  a worker), so cancellation and worker execution cannot both win.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.models import ContentDraft, ContentPublication, SocialAccount
from app.models.scheduling import ScheduledPost, SchedulingHistory
from app.services.audit import record_audit
from app.services.publishing import service as publishing
from app.services.publishing.eligibility import EligibilityReport, evaluate_eligibility, publication_guard
from app.services.publishing.queue import enqueue_publication
from app.services.scheduling.timezones import ensure_utc, local_to_utc, utc_to_local

logger = logging.getLogger("autowok.scheduling")
SCHEDULE_ROLES = {"OWNER", "ADMIN"}


class ScheduleError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _history(
    db: DBSession,
    post: ScheduledPost,
    action: str,
    *,
    user_id: UUID | None = None,
    previous: datetime | None = None,
    new: datetime | None = None,
    **details: object,
) -> None:
    db.add(
        SchedulingHistory(
            scheduled_post_id=post.id,
            action=action,
            previous_scheduled_at=previous,
            new_scheduled_at=new,
            performed_by=user_id,
            details={key: value for key, value in details.items() if value is not None},
        )
    )


def _publication(db: DBSession, post: ScheduledPost) -> ContentPublication | None:
    return db.get(ContentPublication, post.publication_id) if post.publication_id else None


def effective_status(post: ScheduledPost, job: ContentPublication | None) -> str:
    if post.status in {"queued", "processing"} and job is not None:
        if job.status in {"processing", "publishing"}:
            return "processing"
        if job.status == "pending":
            return "queued"
    return post.status


# Validation -----------------------------------------------------------------


@dataclass
class ScheduleTarget:
    draft: ContentDraft
    account: SocialAccount
    scheduled_at: datetime
    scheduled_local: str
    timezone: str
    report: EligibilityReport


def resolve_target(
    db: DBSession,
    *,
    workspace_id: UUID,
    draft_id: UUID,
    social_account_id: UUID,
    scheduled_local: str,
    tz_name: str,
    ambiguous: str | None = None,
    brand_id: UUID | None = None,
    project_id: UUID | None = None,
    exclude_schedule_id: UUID | None = None,
    exclude_publication_id: UUID | None = None,
    now: datetime | None = None,
) -> ScheduleTarget:
    """Validate everything required to schedule (spec checks 3–12)."""
    from app.services.scheduling.timezones import TimezoneError

    draft = db.get(ContentDraft, draft_id)
    if draft is None or draft.project.workspace_id != workspace_id:
        raise ScheduleError("Content not found in this workspace.", 404)
    if project_id is not None and draft.project_id != project_id:
        raise ScheduleError("The selected draft does not belong to the selected content post.")
    account = db.get(SocialAccount, social_account_id)
    if account is None or account.workspace_id != workspace_id:
        raise ScheduleError("Social account not found in this workspace.", 404)
    if brand_id is not None:
        from app.models import Brand

        brand = db.get(Brand, brand_id)
        if brand is None or brand.workspace_id != workspace_id:
            raise ScheduleError("Brand not found in this workspace.", 404)
        if draft.project.brand_id != brand_id:
            raise ScheduleError("The selected content does not belong to the selected brand.")

    try:
        scheduled_at, normalized_local = local_to_utc(scheduled_local, tz_name, ambiguous=ambiguous)
    except TimezoneError as exc:
        raise ScheduleError(str(exc), 422) from exc
    settings = get_settings()
    now = now or utc_now()
    if scheduled_at <= now + timedelta(seconds=settings.schedule_min_lead_seconds):
        raise ScheduleError(
            "The scheduled time must be in the future"
            + (f" (at least {settings.schedule_min_lead_seconds // 60} minute(s) from now)." if settings.schedule_min_lead_seconds >= 60 else ".")
        )
    if scheduled_at > now + timedelta(days=settings.schedule_max_horizon_days):
        raise ScheduleError(f"Posts can be scheduled at most {settings.schedule_max_horizon_days} days ahead.")

    report = evaluate_eligibility(
        db,
        draft=draft,
        account=account,
        exclude_schedule_id=exclude_schedule_id,
        exclude_publication_id=exclude_publication_id,
    )
    if not report.eligible:
        raise ScheduleError(" ".join(report.errors))
    return ScheduleTarget(draft, account, scheduled_at, normalized_local, tz_name, report)


# User actions ---------------------------------------------------------------


def create_schedule(db: DBSession, target: ScheduleTarget, *, user_id: UUID) -> ScheduledPost:
    draft, account = target.draft, target.account
    post = ScheduledPost(
        workspace_id=draft.project.workspace_id,
        project_id=draft.project_id,
        draft_id=draft.id,
        social_account_id=account.id,
        brand_id=draft.project.brand_id,
        platform=draft.platform,
        scheduled_at=target.scheduled_at,
        scheduled_local=target.scheduled_local,
        timezone=target.timezone,
        status="scheduled",
        revision=1,
        content_version_number=draft.version_count,
        active_guard=publication_guard(draft.id, account.id),
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(post)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ScheduleError("This content is already scheduled or published for this account.", 409) from exc
    _history(db, post, "created", user_id=user_id, new=target.scheduled_at, timezone=target.timezone, local=target.scheduled_local)
    record_audit(
        db,
        action="schedule.created",
        resource_type="scheduled_post",
        actor_user_id=user_id,
        workspace_id=post.workspace_id,
        resource_id=post.id,
        metadata={"scheduled_at": target.scheduled_at.isoformat(), "timezone": target.timezone},
    )
    from app.services.automation.events import emit_post_scheduled

    emit_post_scheduled(db, post)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ScheduleError("This content is already scheduled or published for this account.", 409) from exc
    db.refresh(post)
    return post


def _release_queued_job(db: DBSession, post: ScheduledPost, user_id: UUID | None) -> None:
    """Cancel the not-yet-started job of a queued post, or refuse if a worker has it."""
    job = _publication(db, post)
    if job is None:
        return
    if job.status in {"processing", "publishing"}:
        raise ScheduleError("This post is being published right now and can no longer be changed.", 409)
    if job.status == "pending":
        if not publishing.cancel_publication(db, job, user_id=user_id, run_hooks=False):
            raise ScheduleError("This post started publishing and can no longer be changed.", 409)


def update_schedule(
    db: DBSession,
    post: ScheduledPost,
    *,
    user_id: UUID,
    scheduled_local: str | None = None,
    tz_name: str | None = None,
    social_account_id: UUID | None = None,
    ambiguous: str | None = None,
) -> ScheduledPost:
    job = _publication(db, post)
    if post.status == "published":
        raise ScheduleError("Published posts cannot be rescheduled.", 409)
    if post.status == "cancelled":
        raise ScheduleError("Cancelled schedules cannot be changed. Create a new schedule.", 409)
    if post.status == "processing" or (job is not None and job.status in {"processing", "publishing"}):
        raise ScheduleError("This post is being published right now and can no longer be changed.", 409)
    if post.status == "failed" and job is not None and job.outcome_uncertain:
        raise ScheduleError(
            "The last attempt may have published this post. Check the account, then resolve it from the "
            "publishing history before rescheduling.",
            409,
        )

    target = resolve_target(
        db,
        workspace_id=post.workspace_id,
        draft_id=post.draft_id,
        social_account_id=social_account_id or post.social_account_id,
        scheduled_local=scheduled_local or post.scheduled_local,
        tz_name=tz_name or post.timezone,
        ambiguous=ambiguous,
        exclude_schedule_id=post.id,
        # The post's own not-yet-started job is replaced by this update.
        exclude_publication_id=post.publication_id if job is not None and job.status == "pending" else None,
    )
    if post.status == "queued":
        _release_queued_job(db, post, user_id)

    previous = ensure_utc(post.scheduled_at)
    revision = post.revision
    changed_account = target.account.id != post.social_account_id
    result = db.execute(
        update(ScheduledPost)
        .where(ScheduledPost.id == post.id, ScheduledPost.revision == revision, ScheduledPost.status.in_(("scheduled", "queued", "failed")))
        .values(
            scheduled_at=target.scheduled_at,
            scheduled_local=target.scheduled_local,
            timezone=target.timezone,
            social_account_id=target.account.id,
            status="scheduled",
            revision=revision + 1,
            content_version_number=target.draft.version_count,
            active_guard=publication_guard(target.draft.id, target.account.id),
            publication_id=None,
            last_error=None,
            queued_at=None,
            updated_by=user_id,
            updated_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise ScheduleError("This schedule changed while you were editing it. Reload and try again.", 409)
    action = "rescheduled" if previous != target.scheduled_at else "updated"
    _history(
        db,
        post,
        action,
        user_id=user_id,
        previous=previous,
        new=target.scheduled_at,
        timezone=target.timezone,
        local=target.scheduled_local,
        social_account_changed=changed_account or None,
        revision=revision + 1,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ScheduleError("This content is already scheduled or published for that account.", 409) from exc
    db.refresh(post)
    return post


def cancel_schedule(db: DBSession, post: ScheduledPost, *, user_id: UUID) -> ScheduledPost:
    if post.status in {"published", "cancelled"}:
        raise ScheduleError(f"This schedule is already {post.status}.", 409)
    if post.status == "processing":
        raise ScheduleError("This post is being published right now and cannot be cancelled.", 409)
    if post.status == "queued":
        _release_queued_job(db, post, user_id)
    if post.status == "failed":
        job = _publication(db, post)
        if job is not None and job.outcome_uncertain:
            raise ScheduleError(
                "The last attempt may have published this post. Resolve it from the publishing history first.", 409
            )
    now = utc_now()
    result = db.execute(
        update(ScheduledPost)
        .where(ScheduledPost.id == post.id, ScheduledPost.status.in_(("scheduled", "queued", "failed")))
        .values(status="cancelled", cancelled_at=now, active_guard=None, updated_by=user_id, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise ScheduleError("This post started publishing and can no longer be cancelled.", 409)
    _history(db, post, "cancelled", user_id=user_id, previous=ensure_utc(post.scheduled_at))
    record_audit(
        db,
        action="schedule.cancelled",
        resource_type="scheduled_post",
        actor_user_id=user_id,
        workspace_id=post.workspace_id,
        resource_id=post.id,
    )
    db.commit()
    db.refresh(post)
    return post


def retry_schedule(db: DBSession, post: ScheduledPost, *, user_id: UUID, confirm_not_published: bool = False) -> ScheduledPost:
    if post.status != "failed":
        raise ScheduleError("Only failed scheduled posts can be retried.", 409)
    job = _publication(db, post)
    if job is None:
        raise ScheduleError(
            "This post failed before publishing started. Fix the issue, then reschedule it.", 409
        )
    if post.active_guard is None:
        post.active_guard = publication_guard(post.draft_id, post.social_account_id)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise ScheduleError("This content is already scheduled or published for this account.", 409) from exc
    try:
        publishing.retry_publication(db, job, user_id=user_id, confirm_not_published=confirm_not_published)
    except publishing.PublishingConflict as exc:
        db.rollback()
        raise ScheduleError(str(exc), 409) from exc
    db.refresh(post)
    _history(db, post, "retried", user_id=user_id, publication_id=str(job.id))
    db.commit()
    db.refresh(post)
    return post


# Scheduler (runs in the worker) -------------------------------------------


def _fail_due_post(db: DBSession, post: ScheduledPost, message: str, action: str) -> None:
    post.status = "failed"
    post.last_error = message
    post.active_guard = None
    _history(db, post, action, error=message)
    record_audit(
        db,
        action=f"schedule.{action}",
        resource_type="scheduled_post",
        workspace_id=post.workspace_id,
        resource_id=post.id,
        metadata={"error": message[:300]},
    )


def schedule_due_posts(db: DBSession, *, now: datetime | None = None, limit: int = 50) -> int:
    """Turn due scheduled posts into publishing jobs. Safe to run concurrently."""
    now = now or utc_now()
    settings = get_settings()
    rows = (
        db.query(ScheduledPost.id, ScheduledPost.revision)
        .filter(ScheduledPost.status == "scheduled", ScheduledPost.scheduled_at <= now)
        .order_by(ScheduledPost.scheduled_at.asc())
        .limit(limit)
        .all()
    )
    handled = 0
    for row in rows:
        claimed = db.execute(
            update(ScheduledPost)
            .where(
                ScheduledPost.id == row.id,
                ScheduledPost.status == "scheduled",
                ScheduledPost.revision == row.revision,
                ScheduledPost.scheduled_at <= now,
            )
            .values(status="queued", queued_at=now, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            db.rollback()
            continue
        post = db.get(ScheduledPost, row.id, populate_existing=True)
        handled += 1
        lateness = (now - ensure_utc(post.scheduled_at)).total_seconds()
        if lateness > settings.schedule_max_lateness_seconds:
            _fail_due_post(
                db,
                post,
                f"Missed the publishing window: the scheduler was unavailable for {int(lateness // 60)} minutes "
                "after the scheduled time. Reschedule the post.",
                "missed",
            )
            db.commit()
            continue

        draft = db.get(ContentDraft, post.draft_id)
        account = db.get(SocialAccount, post.social_account_id)
        if draft is None or account is None:
            _fail_due_post(db, post, "The content or social account was deleted.", "validation_failed")
            db.commit()
            continue
        report = evaluate_eligibility(
            db,
            draft=draft,
            account=account,
            exclude_schedule_id=post.id,
            expected_version=post.content_version_number,
        )
        if not report.eligible:
            _fail_due_post(db, post, "Publishing was blocked: " + " ".join(report.errors), "validation_failed")
            db.commit()
            continue
        try:
            job, _created = publishing.create_publication(
                db,
                draft=draft,
                account=account,
                report=report,
                requested_by=post.updated_by or post.created_by,
                idempotency_key=f"schedule:{post.id}:{post.revision}",
                source="schedule",
                enqueue=False,
                commit=False,
            )
        except publishing.PublishingConflict as exc:
            # create_publication rolled back the claim; record the failure atomically.
            db.execute(
                update(ScheduledPost)
                .where(ScheduledPost.id == row.id, ScheduledPost.revision == row.revision, ScheduledPost.status == "scheduled")
                .values(status="failed", last_error=str(exc), active_guard=None, updated_at=now)
                .execution_options(synchronize_session=False)
            )
            post = db.get(ScheduledPost, row.id, populate_existing=True)
            _history(db, post, "validation_failed", error=str(exc))
            db.commit()
            continue
        post.publication_id = job.id
        _history(db, post, "queued", publication_id=str(job.id), revision=post.revision)
        db.commit()
        enqueue_publication(job.id)
    return handled


def sync_from_publication(db: DBSession, job: ContentPublication) -> None:
    """Completion hook: mirror the job result onto its scheduled post."""
    if job.source != "schedule":
        return
    post = db.query(ScheduledPost).filter(ScheduledPost.publication_id == job.id).first()
    if post is None or post.status == "cancelled":
        return
    if job.status == "published" and post.status != "published":
        post.status = "published"
        post.published_at = job.published_at or utc_now()
        post.last_error = None
        _history(db, post, "published", external_post_id=job.external_post_id, permalink=job.permalink)
    elif job.status == "failed":
        if post.status != "failed" or post.last_error != job.error_message:
            post.status = "failed"
            post.last_error = job.error_message
            if not job.outcome_uncertain:
                post.active_guard = None
            _history(db, post, "failed", category=job.error_category, error=job.error_message, uncertain=job.outcome_uncertain or None)
    elif job.status == "pending":
        if post.status != "queued" or (job.attempt_count and post.last_error != job.error_message):
            post.status = "queued"
            post.last_error = job.error_message if job.attempt_count else None
            if job.attempt_count:
                _history(
                    db,
                    post,
                    "retry_scheduled",
                    category=job.error_category,
                    next_attempt_at=ensure_utc(job.next_attempt_at).isoformat() if job.next_attempt_at else None,
                )
    elif job.status in {"processing", "publishing"}:
        post.status = "processing"
    elif job.status == "cancelled" and post.status in {"queued", "processing"}:
        post.status = "cancelled"
        post.cancelled_at = job.cancelled_at or utc_now()
        post.active_guard = None
        _history(db, post, "cancelled")


def display_local(post: ScheduledPost, tz_name: str | None = None) -> str:
    return utc_to_local(post.scheduled_at, tz_name or post.timezone)


def register_hooks() -> None:
    if sync_from_publication not in publishing.COMPLETION_HOOKS:
        publishing.COMPLETION_HOOKS.append(sync_from_publication)


register_hooks()
