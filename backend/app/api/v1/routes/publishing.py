from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import authorize_workspace, get_current_user
from app.db.session import get_db
from app.models import ContentDraft, ContentProject, ContentPublication, SocialAccount, User
from app.schemas.publishing import (
    EligibilityRead,
    PublicationRead,
    PublishingAttemptRead,
    PublishRequest,
    PublishValidateRequest,
    RetryRequest,
)
from app.services.publishing.eligibility import EligibilityReport, evaluate_eligibility
from app.services.publishing.service import (
    PublishingConflict,
    cancel_publication,
    create_publication,
    retry_publication,
)

router = APIRouter(tags=["publishing"])

# Publishing to a public brand account is restricted to workspace Owners and
# Admins (the same roles that approve content and connect accounts).
PUBLISH_ROLES = {"OWNER", "ADMIN"}


def publication_read(db: DBSession, job: ContentPublication, *, include_attempts: bool = False) -> PublicationRead:
    project = db.get(ContentProject, job.project_id)
    account = db.get(SocialAccount, job.social_account_id) if job.social_account_id else None
    can_retry = job.status == "failed" and not (job.error_category == "permanent" and not job.requires_user_action)
    return PublicationRead(
        id=job.id,
        workspace_id=job.workspace_id,
        project_id=job.project_id,
        draft_id=job.draft_id,
        social_account_id=job.social_account_id,
        platform=job.platform,
        source=job.source,
        status=job.status,
        stage=job.stage,
        publish_format=(job.platform_response or {}).get("format"),
        caption=job.caption,
        media_asset_ids=list(job.media_asset_ids or []),
        content_version_number=job.content_version_number,
        external_post_id=job.external_post_id,
        permalink=job.permalink,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        next_attempt_at=job.next_attempt_at,
        error_category=job.error_category,
        error_code=job.error_code,
        error_message=job.error_message,
        requires_user_action=job.requires_user_action,
        outcome_uncertain=job.outcome_uncertain,
        can_retry=can_retry,
        can_cancel=job.status == "pending",
        requested_by=job.requested_by,
        confirmed_at=job.confirmed_at,
        started_at=job.started_at,
        published_at=job.published_at,
        completed_at=job.completed_at,
        cancelled_at=job.cancelled_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
        project_title=project.title if project else None,
        account_name=account.display_name if account else None,
        attempts=[PublishingAttemptRead.model_validate(item) for item in job.attempts] if include_attempts else [],
    )


def _eligibility_read(report: EligibilityReport, account: SocialAccount) -> EligibilityRead:
    return EligibilityRead(
        eligible=report.eligible,
        platform=report.platform,
        publish_format=report.publish_format,
        approval_status=report.approval_status,
        content_version_number=report.content_version_number,
        caption=report.caption,
        media_count=len(report.media),
        errors=report.errors,
        warnings=report.warnings,
        social_account_id=account.id,
        account_name=account.display_name,
        account_platform=account.platform,
    )


def _draft_and_account(db: DBSession, user: User, draft_id: UUID, account_id: UUID) -> tuple[ContentDraft, SocialAccount, str]:
    draft = db.query(ContentDraft).filter(ContentDraft.id == draft_id).first()
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found.")
    membership = authorize_workspace(draft.project.workspace_id, user, db)
    account = (
        db.query(SocialAccount)
        .filter(SocialAccount.id == account_id, SocialAccount.workspace_id == draft.project.workspace_id)
        .first()
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Social account not found in this workspace.")
    return draft, account, membership.role


def _get_job(db: DBSession, user: User, job_id: UUID, roles: set[str] | None = None) -> ContentPublication:
    job = db.query(ContentPublication).filter(ContentPublication.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Publishing job not found.")
    authorize_workspace(job.workspace_id, user, db, roles)
    return job


@router.post("/content/drafts/{draft_id}/publishing/validate", response_model=EligibilityRead)
def validate_publishing(
    draft_id: UUID,
    payload: PublishValidateRequest,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> EligibilityRead:
    draft, account, role = _draft_and_account(db, current_user, draft_id, payload.social_account_id)
    report = evaluate_eligibility(db, draft=draft, account=account)
    if role not in PUBLISH_ROLES:
        report.errors.append("Only workspace Owners and Admins can publish.")
    return _eligibility_read(report, account)


@router.post(
    "/content/drafts/{draft_id}/publish",
    response_model=PublicationRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def publish_now(
    draft_id: UUID,
    payload: PublishRequest,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> PublicationRead:
    draft, account, role = _draft_and_account(db, current_user, draft_id, payload.social_account_id)
    if role not in PUBLISH_ROLES:
        raise HTTPException(status_code=403, detail="Only workspace Owners and Admins can publish.")
    if payload.confirm is not True:
        raise HTTPException(status_code=400, detail="Confirm immediate publishing to continue.")
    idempotency_key = payload.idempotency_key or idempotency_key_header or f"auto-{uuid4().hex}"

    existing = (
        db.query(ContentPublication)
        .filter(
            ContentPublication.workspace_id == draft.project.workspace_id,
            ContentPublication.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing is not None:
        if existing.draft_id != draft.id or existing.social_account_id != account.id:
            raise HTTPException(status_code=409, detail="This idempotency key was already used for a different request.")
        return publication_read(db, existing)

    report = evaluate_eligibility(db, draft=draft, account=account)
    if not report.eligible:
        raise HTTPException(status_code=400, detail=" ".join(report.errors))
    try:
        job, _created = create_publication(
            db,
            draft=draft,
            account=account,
            report=report,
            requested_by=current_user.id,
            idempotency_key=idempotency_key,
        )
    except PublishingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return publication_read(db, job)


@router.get("/workspaces/{workspace_id}/publishing/jobs", response_model=list[PublicationRead])
def list_publishing_jobs(
    workspace_id: UUID,
    status_filter: str | None = Query(default=None, alias="status", pattern="^(pending|processing|publishing|published|failed|cancelled)$"),
    project_id: UUID | None = None,
    draft_id: UUID | None = None,
    platform: str | None = Query(default=None, pattern="^(facebook|instagram)$"),
    source: str | None = Query(default=None, pattern="^(manual|schedule)$"),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[PublicationRead]:
    authorize_workspace(workspace_id, current_user, db)
    query = db.query(ContentPublication).filter(ContentPublication.workspace_id == workspace_id)
    if status_filter:
        query = query.filter(ContentPublication.status == status_filter)
    if project_id:
        query = query.filter(ContentPublication.project_id == project_id)
    if draft_id:
        query = query.filter(ContentPublication.draft_id == draft_id)
    if platform:
        query = query.filter(ContentPublication.platform == platform)
    if source:
        query = query.filter(ContentPublication.source == source)
    jobs = query.order_by(ContentPublication.created_at.desc()).limit(limit).all()
    return [publication_read(db, job) for job in jobs]


@router.get("/publishing/jobs/{job_id}", response_model=PublicationRead)
def get_publishing_job(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> PublicationRead:
    return publication_read(db, _get_job(db, current_user, job_id), include_attempts=True)


@router.post("/publishing/jobs/{job_id}/retry", response_model=PublicationRead)
def retry_publishing_job(
    job_id: UUID,
    payload: RetryRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> PublicationRead:
    job = _get_job(db, current_user, job_id, PUBLISH_ROLES)
    try:
        job = retry_publication(
            db, job, user_id=current_user.id, confirm_not_published=bool(payload and payload.confirm_not_published)
        )
    except PublishingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return publication_read(db, job, include_attempts=True)


@router.post("/publishing/jobs/{job_id}/cancel", response_model=PublicationRead)
def cancel_publishing_job(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> PublicationRead:
    job = _get_job(db, current_user, job_id, PUBLISH_ROLES)
    if job.source == "schedule":
        raise HTTPException(status_code=409, detail="Cancel scheduled jobs from the calendar.")
    if not cancel_publication(db, job, user_id=current_user.id):
        raise HTTPException(status_code=409, detail="This job has already started or finished and cannot be cancelled.")
    return publication_read(db, job, include_attempts=True)
