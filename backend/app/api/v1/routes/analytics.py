"""Phase 9 analytics API.

All routes live under ``/workspaces/{workspace_id}/analytics``. Workspace
members can read analytics and export reports; only Owners and Admins can
request a manual refresh. Every brand, account and post id from the browser
is checked against the workspace before use, and inaccessible ids return 404.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import get_current_user, require_workspace_admin, require_workspace_member
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Brand, SocialAccount, User, WorkspaceMembership
from app.models.analytics import ACTIVE_SYNC_STATUSES, AnalyticsSyncJob
from app.schemas.analytics import (
    AccountInsightsRead,
    CompareRead,
    CompareRequest,
    ContentPerformanceRead,
    OverviewRead,
    PlatformComparisonRead,
    PostDetailRead,
    PostListRead,
    ReportRead,
    SummaryRead,
    SyncJobRead,
    SyncRequest,
    SyncRequestRead,
    SyncStatusListRead,
    TimeseriesRead,
)
from app.services.analytics import metrics as M
from app.services.analytics import queries as Q
from app.services.analytics import reports as R
from app.services.analytics import sync as S
from app.services.analytics.summaries import summarize_performance
from app.services.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/workspaces/{workspace_id}/analytics", tags=["analytics"])

MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 28


def _resolve_filters(
    db: DBSession,
    workspace_id: UUID,
    *,
    start: date | None,
    end: date | None,
    brand_id: UUID | None,
    platform: str | None,
    social_account_id: UUID | None,
) -> Q.AnalyticsFilters:
    today = datetime.now(timezone.utc).date()
    end = end or today
    start = start or end - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    if start > end:
        raise HTTPException(status_code=422, detail="The start date must not be after the end date.")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(status_code=422, detail=f"Select a date range of at most {MAX_RANGE_DAYS} days.")
    if brand_id is not None and db.query(Brand).filter(Brand.id == brand_id, Brand.workspace_id == workspace_id).first() is None:
        raise HTTPException(status_code=404, detail="Brand not found.")
    if social_account_id is not None:
        account = (
            db.query(SocialAccount)
            .filter(SocialAccount.id == social_account_id, SocialAccount.workspace_id == workspace_id)
            .first()
        )
        if account is None:
            raise HTTPException(status_code=404, detail="Social account not found in this workspace.")
    filters = Q.AnalyticsFilters(
        workspace_id=workspace_id, start=start, end=end, brand_id=brand_id, platform=platform, social_account_id=social_account_id
    )
    return Q.resolve_accounts(db, filters)


PlatformQuery = Query(default=None, pattern="^(facebook_page|instagram)$")


@router.get("/metrics")
def get_metric_catalogue(
    workspace_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
) -> dict[str, Any]:
    return M.catalogue()


@router.get("/overview", response_model=OverviewRead)
def get_overview(
    workspace_id: UUID,
    start: date | None = None,
    end: date | None = None,
    brand_id: UUID | None = None,
    platform: str | None = PlatformQuery,
    social_account_id: UUID | None = None,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    filters = _resolve_filters(db, workspace_id, start=start, end=end, brand_id=brand_id, platform=platform, social_account_id=social_account_id)
    return Q.overview(db, filters)


@router.get("/timeseries", response_model=TimeseriesRead)
def get_timeseries(
    workspace_id: UUID,
    metric: str = Query(pattern="^[a-z_]{2,64}$"),
    group_by: str = Query(default="platform", pattern="^(platform|account)$"),
    start: date | None = None,
    end: date | None = None,
    brand_id: UUID | None = None,
    platform: str | None = PlatformQuery,
    social_account_id: UUID | None = None,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    if metric not in M.account_metric_keys():
        raise HTTPException(status_code=422, detail="Unknown account metric.")
    filters = _resolve_filters(db, workspace_id, start=start, end=end, brand_id=brand_id, platform=platform, social_account_id=social_account_id)
    return Q.timeseries(db, filters, metric, group_by)


@router.get("/accounts", response_model=list[AccountInsightsRead])
def get_account_insights(
    workspace_id: UUID,
    start: date | None = None,
    end: date | None = None,
    brand_id: UUID | None = None,
    platform: str | None = PlatformQuery,
    social_account_id: UUID | None = None,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> list[dict[str, Any]]:
    filters = _resolve_filters(db, workspace_id, start=start, end=end, brand_id=brand_id, platform=platform, social_account_id=social_account_id)
    return Q.account_insights(db, filters)


@router.get("/accounts/{account_id}", response_model=AccountInsightsRead)
def get_single_account_insights(
    workspace_id: UUID,
    account_id: UUID,
    start: date | None = None,
    end: date | None = None,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    filters = _resolve_filters(db, workspace_id, start=start, end=end, brand_id=None, platform=None, social_account_id=account_id)
    results = Q.account_insights(db, filters)
    if not results:
        raise HTTPException(status_code=404, detail="Social account not found in this workspace.")
    return results[0]


@router.get("/posts", response_model=PostListRead)
def list_post_analytics(
    workspace_id: UUID,
    start: date | None = None,
    end: date | None = None,
    brand_id: UUID | None = None,
    platform: str | None = PlatformQuery,
    social_account_id: UUID | None = None,
    content_format: str | None = Query(default=None, pattern="^[a-z_]{2,40}$"),
    source: str | None = Query(default=None, pattern="^(autowok|external)$"),
    min_engagements: int | None = Query(default=None, ge=0),
    max_engagements: int | None = Query(default=None, ge=0),
    sort: str = Query(default="published_at", pattern="^(published_at|reach|views|engagements|likes|comments|shares|saves|clicks|video_views)$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    filters = _resolve_filters(db, workspace_id, start=start, end=end, brand_id=brand_id, platform=platform, social_account_id=social_account_id)
    return Q.list_posts(
        db,
        filters,
        content_format=content_format,
        source=source,
        min_engagements=min_engagements,
        max_engagements=max_engagements,
        sort=sort,
        order=order,
        offset=offset,
        limit=limit,
    )


@router.get("/posts/{post_id}", response_model=PostDetailRead)
def get_post_analytics(
    workspace_id: UUID,
    post_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    detail = Q.post_detail(db, workspace_id, post_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Post analytics not found.")
    return detail


@router.post("/posts/compare", response_model=CompareRead)
def compare_post_analytics(
    workspace_id: UUID,
    payload: CompareRequest,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    result = Q.compare_posts(db, workspace_id, payload.post_ids)
    if len(result["posts"]) != len(set(payload.post_ids)):
        raise HTTPException(status_code=404, detail="One or more posts were not found in this workspace.")
    return result


@router.get("/platforms/compare", response_model=PlatformComparisonRead)
def get_platform_comparison(
    workspace_id: UUID,
    start: date | None = None,
    end: date | None = None,
    brand_id: UUID | None = None,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    filters = _resolve_filters(db, workspace_id, start=start, end=end, brand_id=brand_id, platform=None, social_account_id=None)
    return Q.platform_comparison(db, filters)


@router.get("/content-performance", response_model=ContentPerformanceRead)
def get_content_performance(
    workspace_id: UUID,
    start: date | None = None,
    end: date | None = None,
    brand_id: UUID | None = None,
    platform: str | None = PlatformQuery,
    social_account_id: UUID | None = None,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    filters = _resolve_filters(db, workspace_id, start=start, end=end, brand_id=brand_id, platform=platform, social_account_id=social_account_id)
    return Q.content_performance(db, filters)


@router.post("/content-performance/summary", response_model=SummaryRead)
def get_content_performance_summary(
    workspace_id: UUID,
    request: Request,
    start: date | None = None,
    end: date | None = None,
    brand_id: UUID | None = None,
    platform: str | None = PlatformQuery,
    social_account_id: UUID | None = None,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    enforce_rate_limit(
        request,
        action="analytics-summary",
        identity=f"{workspace_id}:{current_user.id}",
        limit=10,
        window_seconds=3600,
        category="AI summary",
    )
    filters = _resolve_filters(db, workspace_id, start=start, end=end, brand_id=brand_id, platform=platform, social_account_id=social_account_id)
    performance = Q.content_performance(db, filters)
    return summarize_performance(db, workspace_id, performance)


# Synchronization ---------------------------------------------------------------


def _job_read(db: DBSession, job: AnalyticsSyncJob) -> dict[str, Any]:
    account = db.get(SocialAccount, job.social_account_id)
    data = SyncJobRead.model_validate(job).model_dump()
    data["account_name"] = account.display_name if account else None
    return data


@router.post("/sync", response_model=SyncRequestRead, status_code=status.HTTP_202_ACCEPTED)
def request_analytics_sync(
    workspace_id: UUID,
    payload: SyncRequest,
    request: Request,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.analytics_enabled:
        raise HTTPException(status_code=503, detail="Analytics synchronization is disabled on this server.")
    enforce_rate_limit(
        request,
        action="analytics-refresh",
        identity=f"{workspace_id}:{current_user.id}",
        limit=settings.analytics_manual_refresh_limit_per_hour,
        window_seconds=3600,
        category="Analytics refresh",
    )
    if payload.social_account_id is not None:
        account = (
            db.query(SocialAccount)
            .filter(SocialAccount.id == payload.social_account_id, SocialAccount.workspace_id == workspace_id)
            .first()
        )
        if account is None:
            raise HTTPException(status_code=404, detail="Social account not found in this workspace.")
        accounts = [account]
    else:
        accounts = db.query(SocialAccount).filter(SocialAccount.workspace_id == workspace_id, SocialAccount.platform.in_(M.PLATFORMS)).all()
    jobs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for account in accounts:
        try:
            job = S.request_sync(db, account=account, requested_by=current_user.id)
        except S.SyncConflict as exc:
            if payload.social_account_id is not None:
                raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
            skipped.append({"social_account_id": str(account.id), "account_name": account.display_name, "reason": str(exc)})
            continue
        jobs.append(_job_read(db, job))
    if not jobs and not skipped:
        raise HTTPException(status_code=404, detail="No connected Facebook Page or Instagram account to synchronize.")
    return {"jobs": jobs, "skipped": skipped}


@router.get("/sync/status", response_model=SyncStatusListRead)
def get_sync_status(
    workspace_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    accounts = (
        db.query(SocialAccount)
        .filter(SocialAccount.workspace_id == workspace_id, SocialAccount.platform.in_(M.PLATFORMS))
        .order_by(SocialAccount.created_at)
        .all()
    )
    active = (
        db.query(AnalyticsSyncJob)
        .filter(AnalyticsSyncJob.workspace_id == workspace_id, AnalyticsSyncJob.status.in_(ACTIVE_SYNC_STATUSES))
        .count()
    )
    return {
        "accounts": [Q.sync_status_for(db, account) for account in accounts],
        "active_jobs": active,
        "sync_interval_hours": get_settings().analytics_sync_interval_hours,
    }


@router.get("/sync/history", response_model=list[SyncJobRead])
def get_sync_history(
    workspace_id: UUID,
    social_account_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> list[dict[str, Any]]:
    query = db.query(AnalyticsSyncJob).filter(AnalyticsSyncJob.workspace_id == workspace_id)
    if social_account_id is not None:
        query = query.filter(AnalyticsSyncJob.social_account_id == social_account_id)
    jobs = query.order_by(AnalyticsSyncJob.created_at.desc()).limit(limit).all()
    return [_job_read(db, job) for job in jobs]


# Reports -----------------------------------------------------------------------


@router.get("/reports", response_model=ReportRead)
def get_report(
    workspace_id: UUID,
    start: date | None = None,
    end: date | None = None,
    brand_id: UUID | None = None,
    platform: str | None = PlatformQuery,
    social_account_id: UUID | None = None,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    filters = _resolve_filters(db, workspace_id, start=start, end=end, brand_id=brand_id, platform=platform, social_account_id=social_account_id)
    return R.build_report(db, filters)


@router.get("/reports/export")
def export_report(
    workspace_id: UUID,
    format: str = Query(pattern="^(csv|pdf)$"),
    start: date | None = None,
    end: date | None = None,
    brand_id: UUID | None = None,
    platform: str | None = PlatformQuery,
    social_account_id: UUID | None = None,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> Response:
    filters = _resolve_filters(db, workspace_id, start=start, end=end, brand_id=brand_id, platform=platform, social_account_id=social_account_id)
    report = R.build_report(db, filters)
    filename = f"autowok-analytics-{filters.start.isoformat()}-to-{filters.end.isoformat()}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"}
    if format == "csv":
        return Response(content=R.render_csv(report).encode("utf-8-sig"), media_type="text/csv; charset=utf-8", headers=headers)
    return Response(content=R.render_pdf(report), media_type="application/pdf", headers=headers)
