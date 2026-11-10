"""Publishing job lifecycle: creation, claiming, processing, retry, cancel.

State machine (``content_publications.status``)::

    pending ──claim──▶ processing ──final call──▶ publishing ──▶ published
       ▲                   │                          │
       └── retryable ──────┴──────── failure ─────────┴──▶ failed
    pending ──user cancel──▶ cancelled

Concurrency: a worker claims a job with a single conditional UPDATE. Only one
worker can win; a lease (``lease_expires_at``) lets another worker recover the
job if the first one crashes.
"""

from __future__ import annotations

import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.models import ContentDraft, ContentPublication, PublishingAttempt, SocialAccount
from app.services.audit import record_audit
from app.services.media_urls import SignedUrlNotConfigured, public_media_url
from app.services.meta_graph import MetaGraphError
from app.services.publishing import errors as E
from app.services.publishing.eligibility import EligibilityReport, evaluate_eligibility, publication_guard
from app.services.publishing.meta_publisher import (
    STAGE_PUBLISHING,
    MetaPublisher,
    PublishContext,
    PublishFailure,
)
from app.services.publishing.queue import enqueue_publication
from app.services.publishing.retry import next_attempt_time
from app.services.token_encryption import TokenEncryptionNotConfigured, decrypt_token

logger = logging.getLogger("autowok.publishing")

# Called after a job reaches a terminal or retry-wait state (used by scheduling).
COMPLETION_HOOKS: list[Callable[[DBSession, ContentPublication], None]] = []


class PublishingConflict(Exception):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:6]}"


# Creation -------------------------------------------------------------------


def create_publication(
    db: DBSession,
    *,
    draft: ContentDraft,
    account: SocialAccount,
    report: EligibilityReport,
    requested_by: UUID | None,
    idempotency_key: str,
    source: str = "manual",
    next_attempt_at: datetime | None = None,
    enqueue: bool = True,
    commit: bool = True,
) -> tuple[ContentPublication, bool]:
    """Create a publishing job. Returns (job, created).

    With ``commit=False`` the job is only flushed so the caller can commit it
    atomically with other changes (the scheduler does this); the caller is then
    responsible for committing and enqueueing.
    """
    workspace_id = draft.project.workspace_id
    existing = (
        db.query(ContentPublication)
        .filter(
            ContentPublication.workspace_id == workspace_id,
            ContentPublication.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing is not None:
        if existing.draft_id != draft.id or existing.social_account_id != account.id:
            raise PublishingConflict("This idempotency key was already used for a different publish request.")
        return existing, False

    now = utc_now()
    job = ContentPublication(
        workspace_id=workspace_id,
        project_id=draft.project_id,
        draft_id=draft.id,
        social_account_id=account.id,
        platform=draft.platform,
        media_asset_ids=[str(asset.id) for asset in report.media],
        status="pending",
        source=source,
        requested_by=requested_by,
        idempotency_key=idempotency_key,
        active_guard=publication_guard(draft.id, account.id),
        content_version_number=draft.version_count,
        caption=report.caption,
        stage=None,
        max_attempts=get_settings().publishing_max_attempts,
        next_attempt_at=next_attempt_at,
        confirmed_at=now,
        platform_response={"format": report.publish_format},
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise PublishingConflict("A publishing job for this content and account already exists.") from exc
    record_audit(
        db,
        action="publishing.requested",
        resource_type="content_publication",
        actor_user_id=requested_by,
        workspace_id=workspace_id,
        resource_id=job.id,
        metadata={"platform": job.platform, "social_account_id": str(account.id), "source": source},
    )
    if not commit:
        db.flush()
        return job, True
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PublishingConflict("A publishing job for this content and account already exists.") from exc
    db.refresh(job)
    if enqueue and next_attempt_at is None:
        enqueue_publication(job.id)
    return job, True


# Claiming -------------------------------------------------------------------


def claimable_condition(now: datetime):
    return or_(
        and_(
            ContentPublication.status == "pending",
            or_(ContentPublication.next_attempt_at.is_(None), ContentPublication.next_attempt_at <= now),
        ),
        and_(
            ContentPublication.status.in_(("processing", "publishing")),
            or_(ContentPublication.lease_expires_at.is_(None), ContentPublication.lease_expires_at < now),
        ),
    )


def due_publication_ids(db: DBSession, *, now: datetime | None = None, limit: int = 20) -> list[UUID]:
    now = now or utc_now()
    rows = (
        db.query(ContentPublication.id)
        .filter(claimable_condition(now))
        .order_by(ContentPublication.next_attempt_at.asc(), ContentPublication.created_at.asc())
        .limit(limit)
        .all()
    )
    return [row.id for row in rows]


def claim_publication(db: DBSession, publication_id: UUID, *, worker_id: str, now: datetime | None = None) -> str | None:
    """Atomically claim a job. Returns the status it was claimed from, or None."""
    now = now or utc_now()
    current = db.query(ContentPublication.status).filter(ContentPublication.id == publication_id).first()
    if current is None:
        return None
    previous_status = current.status
    lease = now + timedelta(seconds=get_settings().publishing_lease_seconds)
    result = db.execute(
        update(ContentPublication)
        .where(
            ContentPublication.id == publication_id,
            ContentPublication.status == previous_status,
            claimable_condition(now),
        )
        .values(
            status="processing" if previous_status == "pending" else previous_status,
            locked_by=worker_id,
            lease_expires_at=lease,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if result.rowcount != 1:
        return None
    return previous_status


# Processing -----------------------------------------------------------------


def _record_failure(
    db: DBSession,
    job: ContentPublication,
    attempt: PublishingAttempt,
    failure: E.FailureClassification,
    now: datetime,
) -> None:
    attempt.status = "uncertain" if failure.uncertain else "failed"
    attempt.error_category = failure.category
    attempt.error_code = failure.code
    attempt.error_message = failure.message
    attempt.retryable = failure.retryable
    attempt.finished_at = now
    attempt.stage = job.stage

    job.error_category = failure.category
    job.error_code = failure.code
    job.error_message = failure.message
    job.locked_by = None
    job.lease_expires_at = None
    if failure.retryable and job.attempt_count < job.max_attempts:
        job.status = "pending"
        job.next_attempt_at = next_attempt_time(now, job.attempt_count, failure.category)
        job.requires_user_action = False
    else:
        job.status = "failed"
        job.completed_at = now
        job.requires_user_action = failure.requires_user_action or failure.retryable
        job.outcome_uncertain = failure.uncertain
        if not failure.uncertain:
            # Definite failure: nothing was posted, so release the duplicate
            # guard. Uncertain outcomes keep it until a user resolves them.
            job.active_guard = None

    account = db.get(SocialAccount, job.social_account_id) if job.social_account_id else None
    if account is not None:
        if failure.category == E.TOKEN_EXPIRED:
            account.connection_status = "expired"
            account.last_error_code = "token_expired"
        elif failure.category == E.PERMISSION:
            account.last_error_code = "publish_permission_denied"
    record_audit(
        db,
        action="publishing.attempt_failed",
        resource_type="content_publication",
        workspace_id=job.workspace_id,
        resource_id=job.id,
        metadata={"category": failure.category, "code": failure.code, "status": job.status},
    )


def _run_hooks(db: DBSession, job: ContentPublication) -> None:
    for hook in COMPLETION_HOOKS:
        try:
            hook(db, job)
        except Exception:  # noqa: BLE001 - a hook must never break publishing state
            logger.exception("Publishing completion hook failed for job %s", job.id)
            db.rollback()
    db.commit()


def process_publication(
    db: DBSession,
    publication_id: UUID,
    *,
    worker_id: str | None = None,
    publisher: MetaPublisher | None = None,
    sleep: Callable[[float], None] | None = None,
    poll_interval_seconds: float = 30,
    max_polls: int = 10,
    now: datetime | None = None,
) -> str | None:
    """Claim and process one job. Returns the resulting status, or None if not claimed."""
    worker_id = worker_id or default_worker_id()
    previous_status = claim_publication(db, publication_id, worker_id=worker_id, now=now)
    if previous_status is None:
        return None
    job = db.get(ContentPublication, publication_id, populate_existing=True)
    if job is None:
        return None
    current_time = now or utc_now()
    job.attempt_count += 1
    job.started_at = job.started_at or current_time
    attempt = PublishingAttempt(
        publication_id=job.id,
        attempt_number=job.attempt_count,
        status="running",
        stage=job.stage,
        worker_id=worker_id,
        started_at=current_time,
    )
    db.add(attempt)
    db.commit()

    recovered_from_publish = previous_status in {"processing", "publishing"} and job.stage == STAGE_PUBLISHING
    if recovered_from_publish and job.platform != "instagram":
        # A worker died after sending the final Facebook request. Meta may have
        # created the post, so this must not be retried automatically.
        _record_failure(db, job, attempt, E.classification(E.UNCERTAIN, code="worker_interrupted"), current_time)
        db.commit()
        _run_hooks(db, job)
        return job.status

    draft = db.get(ContentDraft, job.draft_id) if job.draft_id else None
    account = db.get(SocialAccount, job.social_account_id) if job.social_account_id else None
    if draft is None or account is None:
        _record_failure(
            db, job, attempt,
            E.classification(E.VALIDATION, "The content or social account was deleted.", "missing_reference"),
            current_time,
        )
        db.commit()
        _run_hooks(db, job)
        return job.status

    report = evaluate_eligibility(
        db,
        draft=draft,
        account=account,
        exclude_publication_id=job.id,
        expected_version=job.content_version_number,
    )
    if not report.eligible:
        _record_failure(
            db, job, attempt,
            E.classification(E.VALIDATION, "Publishing was blocked: " + " ".join(report.errors), "revalidation_failed"),
            current_time,
        )
        db.commit()
        _run_hooks(db, job)
        return job.status

    try:
        token = decrypt_token(account.credential.encrypted_access_token)
    except (TokenEncryptionNotConfigured, AttributeError):
        _record_failure(
            db, job, attempt,
            E.classification(E.CONFIGURATION, "The stored account credential could not be decrypted. Reconnect the account.", "credential"),
            current_time,
        )
        db.commit()
        _run_hooks(db, job)
        return job.status

    def checkpoint() -> None:
        if job.stage == STAGE_PUBLISHING:
            job.status = "publishing"
        job.lease_expires_at = utc_now() + timedelta(seconds=get_settings().publishing_lease_seconds)
        attempt.stage = job.stage
        db.commit()

    def media_url(asset) -> str:
        return public_media_url(asset.id)

    ctx = PublishContext(
        job=job,
        account=account,
        access_token=token,
        media=report.media,
        caption=job.caption or report.caption,
        publish_format=report.publish_format or "",
        media_url=media_url,
        checkpoint=checkpoint,
        poll_interval_seconds=poll_interval_seconds,
        max_polls=max_polls,
    )
    if sleep is not None:
        ctx.sleep = sleep

    publisher = publisher or MetaPublisher()
    try:
        result = publisher.publish(ctx)
    except PublishFailure as failure:
        _record_failure(db, job, attempt, failure.failure, utc_now())
        db.commit()
        _run_hooks(db, job)
        return job.status
    except MetaGraphError as error:
        failure = E.classify_meta_error(error, final_publish_call=job.stage == STAGE_PUBLISHING, platform=job.platform)
        _record_failure(db, job, attempt, failure, utc_now())
        db.commit()
        _run_hooks(db, job)
        return job.status
    except SignedUrlNotConfigured as exc:
        _record_failure(db, job, attempt, E.classification(E.CONFIGURATION, str(exc), "media_url"), utc_now())
        db.commit()
        _run_hooks(db, job)
        return job.status

    finished = utc_now()
    job.status = "published"
    job.external_post_id = result.external_post_id or job.external_post_id
    job.permalink = result.permalink or job.permalink
    job.platform_response = {**(job.platform_response or {}), **result.summary}
    job.published_at = finished
    job.completed_at = finished
    job.error_category = None
    job.error_code = None
    job.error_message = None
    job.requires_user_action = False
    job.outcome_uncertain = False
    job.locked_by = None
    job.lease_expires_at = None
    attempt.status = "succeeded"
    attempt.finished_at = finished
    attempt.response_summary = result.summary
    record_audit(
        db,
        action="publishing.published",
        resource_type="content_publication",
        workspace_id=job.workspace_id,
        resource_id=job.id,
        metadata={"platform": job.platform, "external_post_id": job.external_post_id},
    )
    db.commit()
    _run_hooks(db, job)
    return job.status


# User actions ---------------------------------------------------------------


def retry_publication(
    db: DBSession,
    job: ContentPublication,
    *,
    user_id: UUID,
    confirm_not_published: bool = False,
    enqueue: bool = True,
) -> ContentPublication:
    if job.status != "failed":
        raise PublishingConflict("Only failed publishing jobs can be retried.")
    if job.outcome_uncertain and not confirm_not_published:
        raise PublishingConflict(
            "This job may already have been published. Check the account, then confirm it was not "
            "published to retry."
        )
    if job.error_category == E.PERMANENT and not job.requires_user_action:
        raise PublishingConflict("Meta permanently rejected this post. Create new content instead.")
    draft = db.get(ContentDraft, job.draft_id) if job.draft_id else None
    account = db.get(SocialAccount, job.social_account_id) if job.social_account_id else None
    if draft is None or account is None:
        raise PublishingConflict("The content or account for this job no longer exists.")
    report = evaluate_eligibility(db, draft=draft, account=account, exclude_publication_id=job.id)
    if not report.eligible:
        raise PublishingConflict("Publishing is still blocked: " + " ".join(report.errors))
    settings = get_settings()
    job.status = "pending"
    job.active_guard = publication_guard(draft.id, account.id)
    job.max_attempts = job.attempt_count + settings.publishing_max_attempts
    job.next_attempt_at = None
    job.requires_user_action = False
    job.outcome_uncertain = False
    job.completed_at = None
    job.content_version_number = draft.version_count
    job.caption = report.caption
    job.media_asset_ids = [str(asset.id) for asset in report.media]
    if confirm_not_published and job.platform != "instagram":
        job.stage = None
    record_audit(
        db,
        action="publishing.retry_requested",
        resource_type="content_publication",
        actor_user_id=user_id,
        workspace_id=job.workspace_id,
        resource_id=job.id,
        metadata={"confirmed_not_published": confirm_not_published},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PublishingConflict("Another publishing job for this content and account is active.") from exc
    db.refresh(job)
    _run_hooks(db, job)
    if enqueue:
        enqueue_publication(job.id)
    return job


def cancel_publication(
    db: DBSession, job: ContentPublication, *, user_id: UUID | None, run_hooks: bool = True
) -> bool:
    """Cancel a job that has not started. Returns False if a worker already claimed it."""
    now = utc_now()
    result = db.execute(
        update(ContentPublication)
        .where(ContentPublication.id == job.id, ContentPublication.status == "pending")
        .values(status="cancelled", cancelled_at=now, completed_at=now, active_guard=None, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        return False
    record_audit(
        db,
        action="publishing.cancelled",
        resource_type="content_publication",
        actor_user_id=user_id,
        workspace_id=job.workspace_id,
        resource_id=job.id,
    )
    db.commit()
    db.refresh(job)
    if run_hooks:
        _run_hooks(db, job)
    return True
