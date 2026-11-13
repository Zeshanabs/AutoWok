"""Analytics synchronization jobs.

Lifecycle (``analytics_sync_jobs.status``)::

    pending ──claim──▶ running ──▶ succeeded | partial
       ▲                 │
       └── retryable ────┴──────▶ failed (after max attempts or on user-action errors)
    pending ──cancel──▶ cancelled

* ``schedule_due_syncs`` creates a scheduled job for every eligible account
  whose last job is older than ``ANALYTICS_SYNC_INTERVAL_HOURS``.
* ``request_sync`` creates a manual job (Owner/Admin) with a per-account
  cooldown. A unique ``active_guard`` guarantees one active job per account.
* ``process_sync_job`` claims a job with a conditional UPDATE (safe with many
  workers), collects account and post metrics, upserts them, and records the
  outcome. Rate limits, network and temporary Meta errors are retried with
  bounded backoff; expired tokens and permission errors stop the job and are
  surfaced to the user. Snapshot upserts are idempotent, so a retried job can
  never duplicate data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.models import SocialAccount
from app.models.analytics import ACTIVE_SYNC_STATUSES, AnalyticsSyncJob
from app.services.analytics import errors as E
from app.services.analytics import metrics as M
from app.services.analytics import storage
from app.services.analytics.collector import CollectedPost, MetaInsightsCollector
from app.services.audit import record_audit
from app.services.meta_graph import MetaGraphClient, MetaGraphError
from app.services.publishing.queue import enqueue_publication
from app.services.publishing.retry import backoff_delay_seconds
from app.services.token_encryption import TokenEncryptionNotConfigured, decrypt_token

logger = logging.getLogger("autowok.analytics")

GraphFactory = Callable[[], MetaGraphClient]


class SyncConflict(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def active_guard(account_id: UUID) -> str:
    return f"analytics:{account_id}"


def eligible_accounts(db: DBSession, workspace_id: UUID | None = None) -> list[SocialAccount]:
    query = db.query(SocialAccount).filter(
        SocialAccount.platform.in_(M.PLATFORMS),
        SocialAccount.connection_status == "connected",
    )
    if workspace_id is not None:
        query = query.filter(SocialAccount.workspace_id == workspace_id)
    return [account for account in query.order_by(SocialAccount.created_at).all() if account.credential is not None]


def analytics_eligibility(account: SocialAccount) -> dict[str, object]:
    """Describe whether insights can be collected for the account and why not."""
    scopes = set(account.granted_scopes or [])
    reasons: list[str] = []
    if account.connection_status != "connected":
        reasons.append(f"The account is {account.connection_status}. Reconnect it in Social account settings.")
    if account.credential is None:
        reasons.append("The account has no stored credential. Reconnect it.")
    if account.platform == M.FACEBOOK:
        missing = [scope for scope in ("read_insights", "pages_read_engagement") if scope not in scopes]
        insights_scope = "read_insights"
    else:
        missing = [scope for scope in ("instagram_manage_insights", "instagram_basic", "pages_read_engagement") if scope not in scopes]
        insights_scope = "instagram_manage_insights"
        if account.account_type not in {"BUSINESS", "MEDIA_CREATOR"}:
            reasons.append("Only Instagram Business or Creator (Professional) accounts have insights.")
    insights_available = insights_scope in scopes and not reasons
    return {
        "can_sync": not reasons,
        "insights_available": insights_available,
        "missing_permissions": missing,
        "reasons": reasons
        + (
            [f"Insights need the {insights_scope} permission. Reconnect Meta and grant it; follower and like counts are still collected."]
            if insights_scope not in scopes
            else []
        ),
    }


# Job creation -----------------------------------------------------------------


def last_job(db: DBSession, account_id: UUID, *, statuses: tuple[str, ...] | None = None) -> AnalyticsSyncJob | None:
    query = db.query(AnalyticsSyncJob).filter(AnalyticsSyncJob.social_account_id == account_id)
    if statuses:
        query = query.filter(AnalyticsSyncJob.status.in_(statuses))
    return query.order_by(AnalyticsSyncJob.created_at.desc()).first()


def active_job(db: DBSession, account_id: UUID) -> AnalyticsSyncJob | None:
    return (
        db.query(AnalyticsSyncJob)
        .filter(AnalyticsSyncJob.social_account_id == account_id, AnalyticsSyncJob.status.in_(ACTIVE_SYNC_STATUSES))
        .first()
    )


def _create_job(
    db: DBSession,
    *,
    account: SocialAccount,
    trigger: str,
    requested_by: UUID | None,
    now: datetime,
) -> AnalyticsSyncJob:
    settings = get_settings()
    today = now.date()
    if storage.snapshot_exists(db, account.id):
        start = today - timedelta(days=settings.analytics_incremental_lookback_days)
    else:
        start = today - timedelta(days=settings.analytics_initial_lookback_days)
    job = AnalyticsSyncJob(
        workspace_id=account.workspace_id,
        social_account_id=account.id,
        platform=account.platform,
        status="pending",
        trigger=trigger,
        requested_by=requested_by,
        active_guard=active_guard(account.id),
        range_start=start,
        range_end=today,
        max_attempts=settings.analytics_sync_max_attempts,
        next_attempt_at=None,
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise SyncConflict("An analytics synchronization is already in progress for this account.") from exc
    return job


def request_sync(
    db: DBSession,
    *,
    account: SocialAccount,
    requested_by: UUID,
    now: datetime | None = None,
    enqueue: bool = True,
) -> AnalyticsSyncJob:
    """Create a manual job for one account, respecting the cooldown."""
    now = now or utc_now()
    settings = get_settings()
    eligibility = analytics_eligibility(account)
    if not eligibility["can_sync"]:
        raise SyncConflict(" ".join(eligibility["reasons"]), status_code=409)
    if active_job(db, account.id) is not None:
        raise SyncConflict("An analytics synchronization is already in progress for this account.")
    recent = last_job(db, account.id, statuses=("succeeded", "partial", "failed"))
    cooldown = timedelta(minutes=settings.analytics_manual_refresh_cooldown_minutes)
    if recent is not None and recent.completed_at is not None and _utc(recent.completed_at) + cooldown > now:
        wait = int((_utc(recent.completed_at) + cooldown - now).total_seconds() // 60) + 1
        raise SyncConflict(
            f"This account was synchronized recently. Try again in about {wait} minute(s).", status_code=429
        )
    job = _create_job(db, account=account, trigger="manual", requested_by=requested_by, now=now)
    record_audit(
        db,
        action="analytics.sync_requested",
        resource_type="analytics_sync_job",
        actor_user_id=requested_by,
        workspace_id=account.workspace_id,
        resource_id=job.id,
        metadata={"platform": account.platform, "social_account_id": str(account.id)},
    )
    db.commit()
    db.refresh(job)
    if enqueue:
        # Wake the worker. The worker treats unknown ids as a no-op hint and
        # picks the job up through the due-job query.
        enqueue_publication(job.id)
    return job


def schedule_due_syncs(db: DBSession, *, now: datetime | None = None) -> int:
    """Create scheduled jobs for eligible accounts whose last job is too old."""
    settings = get_settings()
    if not settings.analytics_enabled:
        return 0
    now = now or utc_now()
    interval = timedelta(hours=settings.analytics_sync_interval_hours)
    created = 0
    for account in eligible_accounts(db):
        if active_job(db, account.id) is not None:
            continue
        previous = last_job(db, account.id)
        if previous is not None and _utc(previous.created_at) + interval > now:
            continue
        try:
            _create_job(db, account=account, trigger="scheduled", requested_by=None, now=now)
            db.commit()
            created += 1
        except SyncConflict:
            continue
    return created


# Claiming ---------------------------------------------------------------------


def _claimable(now: datetime):
    return or_(
        and_(
            AnalyticsSyncJob.status == "pending",
            or_(AnalyticsSyncJob.next_attempt_at.is_(None), AnalyticsSyncJob.next_attempt_at <= now),
        ),
        and_(
            AnalyticsSyncJob.status == "running",
            or_(AnalyticsSyncJob.lease_expires_at.is_(None), AnalyticsSyncJob.lease_expires_at < now),
        ),
    )


def due_sync_job_ids(db: DBSession, *, now: datetime | None = None, limit: int = 10) -> list[UUID]:
    now = now or utc_now()
    rows = (
        db.query(AnalyticsSyncJob.id)
        .filter(_claimable(now))
        .order_by(AnalyticsSyncJob.next_attempt_at.asc(), AnalyticsSyncJob.created_at.asc())
        .limit(limit)
        .all()
    )
    return [row.id for row in rows]


def claim_sync_job(db: DBSession, job_id: UUID, *, worker_id: str, now: datetime | None = None) -> bool:
    now = now or utc_now()
    lease = now + timedelta(seconds=get_settings().analytics_sync_lease_seconds)
    result = db.execute(
        update(AnalyticsSyncJob)
        .where(AnalyticsSyncJob.id == job_id, _claimable(now))
        .values(status="running", locked_by=worker_id, lease_expires_at=lease, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount == 1


# Processing -------------------------------------------------------------------


@dataclass
class SyncOutcome:
    status: str
    records: int
    details: dict


def _finish(job: AnalyticsSyncJob, *, status: str, now: datetime, records: int, details: dict) -> None:
    job.status = status
    job.completed_at = now
    job.records_processed = records
    job.details = details
    job.locked_by = None
    job.lease_expires_at = None
    job.active_guard = None
    job.next_attempt_at = None


def _fail(job: AnalyticsSyncJob, failure: E.CollectionFailure, *, now: datetime, details: dict, account: SocialAccount | None) -> None:
    job.error_category = failure.category
    job.error_code = failure.code
    job.last_error = failure.message
    job.locked_by = None
    job.lease_expires_at = None
    if failure.retryable and job.attempt_count < job.max_attempts:
        delay = failure.retry_after_seconds or backoff_delay_seconds(job.attempt_count, failure.category)
        job.status = "pending"
        job.next_attempt_at = now + timedelta(seconds=delay)
        job.details = {**details, "retry_in_seconds": int(delay)}
        return
    _finish(job, status="failed", now=now, records=job.records_processed, details=details)
    if account is not None:
        if failure.category == E.TOKEN_EXPIRED:
            account.connection_status = "expired"
            account.last_error_code = "token_expired"
        elif failure.category == E.PERMISSION:
            account.last_error_code = "insights_permission_denied"


def process_sync_job(
    db: DBSession,
    job_id: UUID,
    *,
    worker_id: str,
    graph_factory: GraphFactory | None = None,
    now: datetime | None = None,
) -> str | None:
    """Claim and run one job. Returns the resulting status, or None if not claimed."""
    now = now or utc_now()
    # Resolved at call time so tests and operators can swap the Graph client.
    factory: GraphFactory = graph_factory or MetaGraphClient
    if not claim_sync_job(db, job_id, worker_id=worker_id, now=now):
        return None
    job = db.get(AnalyticsSyncJob, job_id, populate_existing=True)
    if job is None:
        return None
    job.attempt_count += 1
    job.started_at = job.started_at or now
    db.commit()

    settings = get_settings()
    details: dict = {"attempt": job.attempt_count, "unavailable": {}, "post_errors": [], "requests": 0}
    account = db.get(SocialAccount, job.social_account_id)
    if account is None:
        _finish(job, status="failed", now=now, records=0, details=details)
        job.error_category = E.PERMANENT
        job.last_error = "The social account no longer exists."
        db.commit()
        return job.status
    eligibility = analytics_eligibility(account)
    if not eligibility["can_sync"]:
        _fail(job, E.failure(E.PERMISSION, "ineligible", " ".join(eligibility["reasons"])), now=now, details=details, account=None)
        db.commit()
        return job.status
    try:
        token = decrypt_token(account.credential.encrypted_access_token)
    except (TokenEncryptionNotConfigured, AttributeError):
        _fail(job, E.failure(E.CONFIGURATION, "credential"), now=now, details=details, account=None)
        db.commit()
        return job.status

    scopes = set(account.granted_scopes or [])
    start: date = job.range_start or (now.date() - timedelta(days=settings.analytics_incremental_lookback_days))
    end: date = job.range_end or now.date()
    post_since = now - timedelta(days=settings.analytics_post_lookback_days)
    records = 0
    try:
        with factory() as graph:
            collector = MetaInsightsCollector(graph)
            # Account-level metrics --------------------------------------
            if account.platform == M.FACEBOOK:
                collection = collector.facebook_account(account.platform_account_id, token, start, end, scopes)
            else:
                collection = collector.instagram_account(account.platform_account_id, token, start, end, scopes)
            details["requests"] += collection.requests
            created, updated = storage.upsert_account_snapshots(
                db, account=account, collection=collection, collected_at=now, api_version=collector.api_version
            )
            details["snapshots_created"] = created
            details["snapshots_updated"] = updated
            details["unavailable"] = dict(collection.unavailable)
            records += created + updated
            db.commit()

            # Post-level metrics -----------------------------------------
            links = storage.find_publication_links(db, account)
            limit = settings.analytics_max_posts_per_sync
            if account.platform == M.FACEBOOK:
                listed = collector.facebook_posts(account.platform_account_id, token, post_since, limit)
            else:
                listed = collector.instagram_media(account.platform_account_id, token, post_since, limit)
            details["requests"] += 1
            seen_ids: set[str] = set()
            posts: list[CollectedPost] = []
            for item in listed:
                item_id = str(item.get("id"))
                try:
                    if account.platform == M.FACEBOOK:
                        post = collector.facebook_post_metrics(item, token, scopes)
                    else:
                        post = collector.instagram_media_metrics(item, token, scopes)
                except MetaGraphError as error:
                    failure = E.classify_collection_error(error)
                    if failure.aborts_sync:
                        raise
                    details["post_errors"].append({"external_post_id": item_id, "category": failure.category, "code": failure.code})
                    continue
                posts.append(post)
                seen_ids.add(post.external_post_id)
                seen_ids.update(post.alternate_ids)

            # Autowok publications missing from the listing (older posts or
            # objects such as video ids) are fetched individually, within budget.
            missing = [external_id for external_id in links if external_id not in seen_ids]
            for external_id in missing[: max(0, limit - len(posts))]:
                try:
                    if account.platform == M.FACEBOOK:
                        item = collector.facebook_post(external_id, token)
                        post = collector.facebook_post_metrics(item, token, scopes)
                    else:
                        item = collector.instagram_media_item(external_id, token)
                        post = collector.instagram_media_metrics(item, token, scopes)
                except MetaGraphError as error:
                    failure = E.classify_collection_error(error)
                    if failure.aborts_sync:
                        raise
                    details["post_errors"].append({"external_post_id": external_id, "category": failure.category, "code": failure.code})
                    continue
                if post.external_post_id != external_id:
                    post.alternate_ids.append(external_id)
                posts.append(post)

            for post in posts:
                publication = links.get(post.external_post_id)
                if publication is None:
                    for alternate in post.alternate_ids:
                        publication = links.get(alternate)
                        if publication is not None:
                            break
                storage.upsert_post(
                    db, account=account, post=post, publication=publication, collected_at=now, api_version=collector.api_version
                )
                records += 1
            details["posts_processed"] = len(posts)
            db.commit()
    except MetaGraphError as error:
        db.rollback()
        job = db.get(AnalyticsSyncJob, job_id, populate_existing=True)
        account = db.get(SocialAccount, job.social_account_id)
        failure = E.classify_collection_error(error)
        if not failure.aborts_sync:
            failure = E.failure(E.PERMANENT, failure.code, failure.message)
        job.records_processed = records
        _fail(job, failure, now=utc_now(), details=details, account=account)
        record_audit(
            db,
            action="analytics.sync_failed",
            resource_type="analytics_sync_job",
            workspace_id=job.workspace_id,
            resource_id=job.id,
            metadata={"category": failure.category, "code": failure.code, "status": job.status},
        )
        _emit_finished(db, job)
        db.commit()
        return job.status

    permission_gaps = [key for key, reason in details["unavailable"].items() if str(reason).startswith("missing_permission")]
    status = "partial" if permission_gaps or details["post_errors"] else "succeeded"
    if permission_gaps:
        details["notice"] = "Some metrics are unavailable because the Meta insights permission was not granted."
    _finish(job, status=status, now=utc_now(), records=records, details=details)
    job.error_category = None
    job.error_code = None
    job.last_error = None
    account.last_error_code = None if account.last_error_code == "insights_permission_denied" else account.last_error_code
    record_audit(
        db,
        action="analytics.sync_completed",
        resource_type="analytics_sync_job",
        workspace_id=job.workspace_id,
        resource_id=job.id,
        metadata={"status": status, "records": records, "platform": account.platform},
    )
    _emit_finished(db, job)
    db.commit()
    return job.status


def _emit_finished(db: DBSession, job: AnalyticsSyncJob) -> None:
    """Phase 10: record an automation event when a job reaches a final state."""
    try:
        from app.services.automation.events import emit_sync_finished

        emit_sync_finished(db, job)
    except Exception:  # noqa: BLE001 - automations must never break synchronization
        logger.exception("Could not record automation event for analytics job %s", job.id)


def run_due_syncs(db: DBSession, *, worker_id: str = "analytics", graph_factory: GraphFactory | None = None, limit: int = 5) -> int:
    processed = 0
    for job_id in due_sync_job_ids(db, limit=limit):
        try:
            if process_sync_job(db, job_id, worker_id=worker_id, graph_factory=graph_factory) is not None:
                processed += 1
        except Exception:  # noqa: BLE001 - one bad job must not stop the others
            logger.exception("Analytics sync job %s failed unexpectedly", job_id)
            db.rollback()
    return processed


def cancel_pending_jobs_for_account(db: DBSession, account_id: UUID) -> int:
    now = utc_now()
    result = db.execute(
        update(AnalyticsSyncJob)
        .where(AnalyticsSyncJob.social_account_id == account_id, AnalyticsSyncJob.status == "pending")
        .values(status="cancelled", completed_at=now, active_guard=None, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount
