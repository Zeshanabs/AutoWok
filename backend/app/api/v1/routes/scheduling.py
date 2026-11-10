from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import authorize_workspace, get_current_user
from app.api.v1.routes.publishing import publication_read
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Brand, ContentDraft, ContentProject, ContentPublication, SocialAccount, User
from app.models.scheduling import ACTIVE_SCHEDULE_STATUSES, ScheduledPost, SchedulingHistory
from app.schemas.scheduling import (
    CalendarItem,
    CalendarRead,
    PreferencesRead,
    PreferencesUpdate,
    QueueStatusRead,
    ScheduleCreate,
    ScheduledPostRead,
    SchedulingHistoryRead,
    ScheduleReschedule,
    ScheduleRetry,
    ScheduleUpdate,
    TimezoneList,
    UnscheduledItem,
)
from app.services.publishing.eligibility import compose_caption
from app.services.scheduling import service as scheduling
from app.services.scheduling.timezones import (
    TimezoneError,
    calendar_range,
    common_timezones,
    ensure_utc,
    get_zone,
    is_valid_timezone,
    utc_offset_label,
    utc_to_local,
)

router = APIRouter(tags=["scheduling"])
STATUS_PATTERN = "^(scheduled|queued|processing|published|failed|cancelled)$"


def _preview(text: str | None, limit: int = 140) -> str | None:
    if not text:
        return None
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _user_timezone(user: User) -> str:
    return user.timezone if user.timezone and is_valid_timezone(user.timezone) else get_settings().default_timezone


def _resolve_timezone(user: User, requested: str | None) -> str:
    tz_name = requested or _user_timezone(user)
    try:
        get_zone(tz_name)
    except TimezoneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return tz_name


def _can_manage(role: str) -> bool:
    return role in scheduling.SCHEDULE_ROLES


def _post_read(db: DBSession, post: ScheduledPost, *, role: str, detail: bool = False) -> ScheduledPostRead:
    job = db.get(ContentPublication, post.publication_id) if post.publication_id else None
    draft = db.get(ContentDraft, post.draft_id)
    project = db.get(ContentProject, post.project_id)
    account = db.get(SocialAccount, post.social_account_id)
    brand = db.get(Brand, post.brand_id) if post.brand_id else None
    effective = scheduling.effective_status(post, job)
    manage = _can_manage(role)
    history: list[SchedulingHistoryRead] = []
    if detail:
        users = {user.id: user.full_name for user in db.query(User).filter(User.id.in_([h.performed_by for h in post.history if h.performed_by])).all()}
        history = [
            SchedulingHistoryRead(
                id=item.id,
                action=item.action,
                previous_scheduled_at=item.previous_scheduled_at,
                new_scheduled_at=item.new_scheduled_at,
                performed_by=item.performed_by,
                performed_by_name=users.get(item.performed_by) if item.performed_by else "System",
                details=item.details or {},
                created_at=item.created_at,
            )
            for item in post.history
        ]
    content_changed = draft is not None and draft.version_count != post.content_version_number and effective in ACTIVE_SCHEDULE_STATUSES
    return ScheduledPostRead(
        id=post.id,
        workspace_id=post.workspace_id,
        project_id=post.project_id,
        draft_id=post.draft_id,
        social_account_id=post.social_account_id,
        brand_id=post.brand_id,
        platform=post.platform,
        scheduled_at=ensure_utc(post.scheduled_at),
        scheduled_local=post.scheduled_local,
        timezone=post.timezone,
        utc_offset=utc_offset_label(post.scheduled_at, post.timezone),
        status=effective,
        stored_status=post.status,
        revision=post.revision,
        content_version_number=post.content_version_number,
        current_content_version=draft.version_count if draft else None,
        content_changed=content_changed,
        approval_status=project.status if project else None,
        publication_id=post.publication_id,
        last_error=post.last_error,
        created_by=post.created_by,
        updated_by=post.updated_by,
        created_at=post.created_at,
        updated_at=post.updated_at,
        queued_at=post.queued_at,
        cancelled_at=post.cancelled_at,
        published_at=post.published_at,
        title=(draft.title if draft and draft.title else None) or (project.title if project else None),
        caption_preview=_preview(compose_caption(draft)) if draft else None,
        brand_name=brand.name if brand else None,
        account_name=account.display_name if account else None,
        account_platform=account.platform if account else None,
        account_status=account.connection_status if account else None,
        permalink=job.permalink if job else None,
        can_edit=manage and effective in {"scheduled", "queued", "failed"} and not (job is not None and job.outcome_uncertain and effective == "failed"),
        can_cancel=manage and effective in {"scheduled", "queued", "failed"} and not (job is not None and job.outcome_uncertain and effective == "failed"),
        can_retry=manage
        and effective == "failed"
        and job is not None
        and job.status == "failed"
        and not (job.error_category == "permanent" and not job.requires_user_action),
        publication=publication_read(db, job, include_attempts=detail) if job is not None else None,
        history=history,
    )


def _get_post(db: DBSession, user: User, schedule_id: UUID) -> tuple[ScheduledPost, str]:
    post = db.query(ScheduledPost).filter(ScheduledPost.id == schedule_id).first()
    if post is None:
        raise HTTPException(status_code=404, detail="Scheduled post not found.")
    membership = authorize_workspace(post.workspace_id, user, db)
    return post, membership.role


def _require_manager(role: str) -> None:
    if not _can_manage(role):
        raise HTTPException(status_code=403, detail="Only workspace Owners and Admins can schedule posts.")


def _schedule_error(exc: scheduling.ScheduleError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


# Scheduled posts ------------------------------------------------------------


@router.post(
    "/workspaces/{workspace_id}/scheduled-posts",
    response_model=ScheduledPostRead,
    status_code=status.HTTP_201_CREATED,
)
def create_scheduled_post(
    workspace_id: UUID,
    payload: ScheduleCreate,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ScheduledPostRead:
    membership = authorize_workspace(workspace_id, current_user, db)
    _require_manager(membership.role)
    if payload.confirm is not True:
        raise HTTPException(status_code=400, detail="Confirm the schedule to continue.")
    try:
        target = scheduling.resolve_target(
            db,
            workspace_id=workspace_id,
            draft_id=payload.draft_id,
            social_account_id=payload.social_account_id,
            scheduled_local=payload.scheduled_local,
            tz_name=payload.timezone,
            ambiguous=payload.ambiguous,
            brand_id=payload.brand_id,
            project_id=payload.project_id,
        )
        post = scheduling.create_schedule(db, target, user_id=current_user.id)
    except scheduling.ScheduleError as exc:
        raise _schedule_error(exc) from exc
    return _post_read(db, post, role=membership.role, detail=True)


@router.get("/workspaces/{workspace_id}/scheduled-posts", response_model=list[ScheduledPostRead])
def list_scheduled_posts(
    workspace_id: UUID,
    status_filter: str | None = Query(default=None, alias="status", pattern=STATUS_PATTERN),
    upcoming: bool = False,
    start: datetime | None = None,
    end: datetime | None = None,
    brand_id: UUID | None = None,
    platform: str | None = Query(default=None, pattern="^(facebook|instagram)$"),
    social_account_id: UUID | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[ScheduledPostRead]:
    membership = authorize_workspace(workspace_id, current_user, db)
    query = db.query(ScheduledPost).filter(ScheduledPost.workspace_id == workspace_id)
    if upcoming:
        query = query.filter(ScheduledPost.status.in_(ACTIVE_SCHEDULE_STATUSES))
    if start:
        query = query.filter(ScheduledPost.scheduled_at >= ensure_utc(start))
    if end:
        query = query.filter(ScheduledPost.scheduled_at < ensure_utc(end))
    if brand_id:
        query = query.filter(ScheduledPost.brand_id == brand_id)
    if platform:
        query = query.filter(ScheduledPost.platform == platform)
    if social_account_id:
        query = query.filter(ScheduledPost.social_account_id == social_account_id)
    posts = query.order_by(ScheduledPost.scheduled_at.asc()).limit(limit).all()
    reads = [_post_read(db, post, role=membership.role) for post in posts]
    if status_filter:
        reads = [read for read in reads if read.status == status_filter]
    return reads


@router.get("/scheduled-posts/{schedule_id}", response_model=ScheduledPostRead)
def get_scheduled_post(
    schedule_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ScheduledPostRead:
    post, role = _get_post(db, current_user, schedule_id)
    return _post_read(db, post, role=role, detail=True)


@router.get("/scheduled-posts/{schedule_id}/history", response_model=list[SchedulingHistoryRead])
def get_scheduling_history(
    schedule_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[SchedulingHistoryRead]:
    post, role = _get_post(db, current_user, schedule_id)
    return _post_read(db, post, role=role, detail=True).history


@router.patch("/scheduled-posts/{schedule_id}", response_model=ScheduledPostRead)
def update_scheduled_post(
    schedule_id: UUID,
    payload: ScheduleUpdate,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ScheduledPostRead:
    post, role = _get_post(db, current_user, schedule_id)
    _require_manager(role)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field is required.")
    try:
        post = scheduling.update_schedule(
            db,
            post,
            user_id=current_user.id,
            scheduled_local=payload.scheduled_local,
            tz_name=payload.timezone,
            social_account_id=payload.social_account_id,
            ambiguous=payload.ambiguous,
        )
    except scheduling.ScheduleError as exc:
        raise _schedule_error(exc) from exc
    return _post_read(db, post, role=role, detail=True)


@router.post("/scheduled-posts/{schedule_id}/reschedule", response_model=ScheduledPostRead)
def reschedule_post(
    schedule_id: UUID,
    payload: ScheduleReschedule,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ScheduledPostRead:
    post, role = _get_post(db, current_user, schedule_id)
    _require_manager(role)
    try:
        post = scheduling.update_schedule(
            db,
            post,
            user_id=current_user.id,
            scheduled_local=payload.scheduled_local,
            tz_name=payload.timezone,
            ambiguous=payload.ambiguous,
        )
    except scheduling.ScheduleError as exc:
        raise _schedule_error(exc) from exc
    return _post_read(db, post, role=role, detail=True)


@router.post("/scheduled-posts/{schedule_id}/cancel", response_model=ScheduledPostRead)
def cancel_scheduled_post(
    schedule_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ScheduledPostRead:
    post, role = _get_post(db, current_user, schedule_id)
    _require_manager(role)
    try:
        post = scheduling.cancel_schedule(db, post, user_id=current_user.id)
    except scheduling.ScheduleError as exc:
        raise _schedule_error(exc) from exc
    return _post_read(db, post, role=role, detail=True)


@router.post("/scheduled-posts/{schedule_id}/retry", response_model=ScheduledPostRead)
def retry_scheduled_post(
    schedule_id: UUID,
    payload: ScheduleRetry | None = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ScheduledPostRead:
    post, role = _get_post(db, current_user, schedule_id)
    _require_manager(role)
    try:
        post = scheduling.retry_schedule(
            db, post, user_id=current_user.id, confirm_not_published=bool(payload and payload.confirm_not_published)
        )
    except scheduling.ScheduleError as exc:
        raise _schedule_error(exc) from exc
    return _post_read(db, post, role=role, detail=True)


# Calendar -------------------------------------------------------------------


@router.get("/workspaces/{workspace_id}/calendar", response_model=CalendarRead)
def get_calendar(
    workspace_id: UUID,
    view: str = Query(default="month", pattern="^(month|week|day|list)$"),
    anchor: date | None = Query(default=None, alias="date"),
    timezone_name: str | None = Query(default=None, alias="timezone", max_length=64),
    brand_id: UUID | None = None,
    platform: str | None = Query(default=None, pattern="^(facebook|instagram)$"),
    social_account_id: UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status", pattern=STATUS_PATTERN),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> CalendarRead:
    membership = authorize_workspace(workspace_id, current_user, db)
    tz_name = _resolve_timezone(current_user, timezone_name)
    zone = get_zone(tz_name)
    if anchor is None:
        anchor = datetime.now(zone).date()
    range_start, range_end, days = calendar_range(view, anchor, tz_name)

    brands = {brand.id: brand.name for brand in db.query(Brand).filter(Brand.workspace_id == workspace_id).all()}
    accounts = {account.id: account for account in db.query(SocialAccount).filter(SocialAccount.workspace_id == workspace_id).all()}
    items: list[CalendarItem] = []

    schedule_query = db.query(ScheduledPost).filter(
        ScheduledPost.workspace_id == workspace_id,
        ScheduledPost.scheduled_at >= range_start,
        ScheduledPost.scheduled_at < range_end,
    )
    if brand_id:
        schedule_query = schedule_query.filter(ScheduledPost.brand_id == brand_id)
    if platform:
        schedule_query = schedule_query.filter(ScheduledPost.platform == platform)
    if social_account_id:
        schedule_query = schedule_query.filter(ScheduledPost.social_account_id == social_account_id)
    for post in schedule_query.all():
        read = _post_read(db, post, role=membership.role)
        local = ensure_utc(post.scheduled_at).astimezone(zone)
        items.append(
            CalendarItem(
                kind="scheduled",
                id=post.id,
                scheduled_post_id=post.id,
                publication_id=post.publication_id,
                project_id=post.project_id,
                draft_id=post.draft_id,
                title=read.title,
                caption_preview=read.caption_preview,
                brand_id=post.brand_id,
                brand_name=read.brand_name,
                platform=post.platform,
                social_account_id=post.social_account_id,
                account_name=read.account_name,
                at=ensure_utc(post.scheduled_at),
                local_time=local.strftime("%H:%M"),
                local_date=local.date(),
                timezone=tz_name,
                status=read.status,
                approval_status=read.approval_status,
                content_changed=read.content_changed,
                last_error=read.last_error,
                permalink=read.permalink,
                can_edit=read.can_edit,
                can_cancel=read.can_cancel,
            )
        )

    # Immediate (manual) publications appear on the day they were published or requested.
    job_query = db.query(ContentPublication).filter(
        ContentPublication.workspace_id == workspace_id,
        ContentPublication.source == "manual",
        ContentPublication.status != "cancelled",
        or_(
            ContentPublication.published_at.between(range_start, range_end),
            (ContentPublication.published_at.is_(None)) & ContentPublication.created_at.between(range_start, range_end),
        ),
    )
    if platform:
        job_query = job_query.filter(ContentPublication.platform == platform)
    if social_account_id:
        job_query = job_query.filter(ContentPublication.social_account_id == social_account_id)
    for job in job_query.all():
        project = db.get(ContentProject, job.project_id)
        if project is None or (brand_id and project.brand_id != brand_id):
            continue
        at = ensure_utc(job.published_at or job.created_at)
        local = at.astimezone(zone)
        account = accounts.get(job.social_account_id) if job.social_account_id else None
        items.append(
            CalendarItem(
                kind="published",
                id=job.id,
                scheduled_post_id=None,
                publication_id=job.id,
                project_id=job.project_id,
                draft_id=job.draft_id,
                title=project.title,
                caption_preview=_preview(job.caption),
                brand_id=project.brand_id,
                brand_name=brands.get(project.brand_id) if project.brand_id else None,
                platform=job.platform,
                social_account_id=job.social_account_id,
                account_name=account.display_name if account else None,
                at=at,
                local_time=local.strftime("%H:%M"),
                local_date=local.date(),
                timezone=tz_name,
                status={"pending": "queued", "publishing": "processing"}.get(job.status, job.status),
                approval_status=project.status,
                last_error=job.error_message,
                permalink=job.permalink,
            )
        )
    if status_filter:
        items = [item for item in items if item.status == status_filter]
    items.sort(key=lambda item: item.at)

    # Approved drafts that are not yet scheduled or published anywhere.
    scheduled_drafts = {
        row.draft_id
        for row in db.query(ScheduledPost.draft_id).filter(
            ScheduledPost.workspace_id == workspace_id,
            ScheduledPost.status.in_((*ACTIVE_SCHEDULE_STATUSES, "published")),
        )
    }
    published_drafts = {
        row.draft_id
        for row in db.query(ContentPublication.draft_id).filter(
            ContentPublication.workspace_id == workspace_id, ContentPublication.status == "published"
        )
    }
    draft_query = (
        db.query(ContentDraft)
        .join(ContentProject, ContentProject.id == ContentDraft.project_id)
        .filter(ContentProject.workspace_id == workspace_id, ContentProject.status == "approved", ContentDraft.status == "approved")
    )
    if brand_id:
        draft_query = draft_query.filter(ContentProject.brand_id == brand_id)
    if platform:
        draft_query = draft_query.filter(ContentDraft.platform == platform)
    unscheduled = [
        UnscheduledItem(
            project_id=draft.project_id,
            draft_id=draft.id,
            title=draft.title or draft.project.title,
            caption_preview=_preview(compose_caption(draft)),
            platform=draft.platform,
            brand_id=draft.project.brand_id,
            brand_name=brands.get(draft.project.brand_id) if draft.project.brand_id else None,
        )
        for draft in draft_query.order_by(ContentProject.approved_at.desc()).limit(50).all()
        if draft.id not in scheduled_drafts and draft.id not in published_drafts
    ]
    return CalendarRead(
        view=view,
        timezone=tz_name,
        anchor_date=anchor,
        range_start=range_start,
        range_end=range_end,
        days=days,
        items=items,
        unscheduled=unscheduled,
    )


# Queue ----------------------------------------------------------------------


@router.get("/workspaces/{workspace_id}/publishing/queue", response_model=QueueStatusRead)
def get_publishing_queue(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> QueueStatusRead:
    membership = authorize_workspace(workspace_id, current_user, db)
    jobs = db.query(ContentPublication).filter(ContentPublication.workspace_id == workspace_id).all()
    counts = {key: 0 for key in ("pending", "processing", "publishing", "published", "failed", "cancelled")}
    for job in jobs:
        counts[job.status] = counts.get(job.status, 0) + 1
    posts = db.query(ScheduledPost).filter(ScheduledPost.workspace_id == workspace_id).all()
    schedule_counts = {key: 0 for key in ("scheduled", "queued", "processing", "published", "failed", "cancelled")}
    for post in posts:
        schedule_counts[post.status] = schedule_counts.get(post.status, 0) + 1
    upcoming_posts = sorted(
        (post for post in posts if post.status == "scheduled"), key=lambda post: ensure_utc(post.scheduled_at)
    )
    active = [job for job in jobs if job.status in {"processing", "publishing"} or (job.status == "pending" and job.attempt_count == 0)]
    retrying = [job for job in jobs if job.status == "pending" and job.attempt_count > 0]
    attention = sorted(
        (job for job in jobs if job.status == "failed" and job.requires_user_action),
        key=lambda job: ensure_utc(job.updated_at),
        reverse=True,
    )[:25]
    return QueueStatusRead(
        counts=counts,
        schedule_counts=schedule_counts,
        next_scheduled_at=ensure_utc(upcoming_posts[0].scheduled_at) if upcoming_posts else None,
        active_jobs=[publication_read(db, job) for job in active],
        retrying_jobs=[publication_read(db, job) for job in retrying],
        attention_jobs=[publication_read(db, job) for job in attention],
        upcoming=[_post_read(db, post, role=membership.role) for post in upcoming_posts[:20]],
    )


# Preferences ----------------------------------------------------------------


@router.get("/me/preferences", response_model=PreferencesRead)
def get_preferences(current_user: User = Depends(get_current_user)) -> PreferencesRead:
    default = get_settings().default_timezone
    return PreferencesRead(
        timezone=_user_timezone(current_user),
        timezone_is_default=not current_user.timezone,
        default_timezone=default,
    )


@router.patch("/me/preferences", response_model=PreferencesRead)
def update_preferences(
    payload: PreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> PreferencesRead:
    if payload.timezone:
        try:
            get_zone(payload.timezone)
        except TimezoneError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    user = db.get(User, current_user.id)
    user.timezone = payload.timezone or None
    db.commit()
    db.refresh(user)
    return get_preferences(user)


@router.get("/timezones", response_model=TimezoneList)
def list_timezones() -> TimezoneList:
    return TimezoneList(timezones=common_timezones())


__all__ = ["router", "utc_to_local"]
