from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import get_current_user
from app.db.session import get_db
from app.integrations.research.services.citation_service import CitationValidationService
from app.integrations.research.services.research_service import ResearchEngineService
from app.models import Brand, ResearchFinding, ResearchProject, ResearchQuery, ResearchReport, ResearchSource, User, WorkspaceMembership
from app.schemas.research import (
    ResearchExportRead,
    ResearchFindingRead,
    ResearchProjectCreate,
    ResearchProjectRead,
    ResearchProjectUpdate,
    ResearchReportRead,
    ResearchSourceRead,
    ResearchStatus,
    ResearchStatusRead,
)

router = APIRouter(tags=["research"])


def _workspace_membership(db: DBSession, user: User, workspace_id: UUID) -> WorkspaceMembership:
    membership = (
        db.query(WorkspaceMembership)
        .filter(WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.user_id == user.id)
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    return membership


def _read_project(project: ResearchProject) -> ResearchProjectRead:
    return ResearchProjectRead.model_validate(project)


def _validate_brand(db: DBSession, workspace_id: UUID, brand_id: UUID | None) -> None:
    if brand_id is None:
        return
    brand = db.query(Brand).filter(Brand.id == brand_id, Brand.workspace_id == workspace_id).first()
    if brand is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brand not found in this workspace.")


def _build_source_read(source: ResearchSource) -> ResearchSourceRead:
    return ResearchSourceRead.model_validate(source)


def _build_finding_read(finding: ResearchFinding) -> ResearchFindingRead:
    return ResearchFindingRead.model_validate(finding)


def _build_report_read(report: ResearchReport | None) -> ResearchReportRead | None:
    if report is None:
        return None
    return ResearchReportRead.model_validate(report)


@router.post("/research", response_model=ResearchProjectRead, status_code=status.HTTP_201_CREATED)
def create_research_project(
    payload: ResearchProjectCreate,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ResearchProjectRead:
    membership = _workspace_membership(db, current_user, payload.workspace_id)
    _validate_brand(db, payload.workspace_id, payload.brand_id)
    project = ResearchProject(
        workspace_id=payload.workspace_id,
        brand_id=payload.brand_id,
        created_by=current_user.id,
        title=payload.title,
        research_question=payload.research_question,
        category=payload.category,
        target_audience=payload.target_audience,
        geographic_scope=payload.geographic_scope,
        language=payload.language,
        recency_preference=payload.recency_preference,
        research_depth=payload.research_depth,
        status=ResearchStatus.PENDING.value,
        current_stage=ResearchStatus.PENDING.value,
    )
    db.add(project)
    db.flush()
    service = ResearchEngineService(db)
    for keyword in payload.optional_keywords or []:
        clean = " ".join(str(keyword).split())
        if clean:
            db.add(ResearchQuery(research_id=project.id, query=clean, query_type="keyword", status="PENDING"))
    if not payload.optional_keywords:
        service.create_queries(project)
    db.commit()
    db.refresh(project)
    return _read_project(project)


@router.post(
    "/workspaces/{workspace_id}/research",
    response_model=ResearchProjectRead,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace_research_project(
    workspace_id: UUID,
    payload: ResearchProjectCreate,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ResearchProjectRead:
    payload.workspace_id = workspace_id
    return create_research_project(payload=payload, current_user=current_user, db=db)


@router.get("/research", response_model=list[ResearchProjectRead])
def list_research_projects(
    workspace_id: UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[ResearchProjectRead]:
    if workspace_id is not None:
        _workspace_membership(db, current_user, workspace_id)
        projects = (
            db.query(ResearchProject)
            .filter(ResearchProject.workspace_id == workspace_id)
            .order_by(ResearchProject.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_read_project(project) for project in projects]

    workspace_ids = [
        row.workspace_id
        for row in db.query(WorkspaceMembership.workspace_id)
        .filter(WorkspaceMembership.user_id == current_user.id)
        .all()
    ]
    if not workspace_ids:
        return []
    projects = (
        db.query(ResearchProject)
        .filter(ResearchProject.workspace_id.in_(workspace_ids))
        .order_by(ResearchProject.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_read_project(project) for project in projects]


@router.get("/research/{research_id}", response_model=ResearchProjectRead)
def get_research_project(
    research_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ResearchProjectRead:
    project = db.query(ResearchProject).filter(ResearchProject.id == research_id).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    return _read_project(project)


@router.patch("/research/{research_id}", response_model=ResearchProjectRead)
def update_research_project(
    research_id: UUID,
    payload: ResearchProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ResearchProjectRead:
    project = db.query(ResearchProject).filter(ResearchProject.id == research_id).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="At least one field is required.")
    for field, value in changes.items():
        if value is None:
            continue
        setattr(project, field, value)
    project.updated_at = datetime.now(timezone.utc)
    if project.status == ResearchStatus.COMPLETED.value:
        project.completed_at = project.completed_at or datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)
    return _read_project(project)


@router.delete("/research/{research_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_research_project(
    research_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    project = db.query(ResearchProject).filter(ResearchProject.id == research_id).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    db.delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/research/{research_id}/run", response_model=ResearchProjectRead)
def run_research_project(
    research_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ResearchProjectRead:
    project = db.query(ResearchProject).filter(ResearchProject.id == research_id).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    service = ResearchEngineService(db)
    project.status = ResearchStatus.SEARCHING.value
    project.current_stage = ResearchStatus.SEARCHING.value
    project.updated_at = datetime.now(timezone.utc)
    try:
        provider_config = service.ensure_search_provider()
    except RuntimeError as exc:
        project.status = ResearchStatus.FAILED.value
        project.current_stage = ResearchStatus.FAILED.value
        project.updated_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    queries = service.create_queries(project)
    results = service.search(project)
    project.status = ResearchStatus.RETRIEVING.value
    project.current_stage = ResearchStatus.RETRIEVING.value
    project.updated_at = datetime.now(timezone.utc)
    if results:
        for result in results:
            service.persist_source_result(project, result)

    project.status = ResearchStatus.ANALYZING.value
    project.current_stage = ResearchStatus.ANALYZING.value
    project.updated_at = datetime.now(timezone.utc)
    service.create_default_report(project, generated_by_model=(provider_config.name or "configured"))

    project.status = ResearchStatus.COMPLETED.value
    project.current_stage = ResearchStatus.COMPLETED.value
    project.completed_at = datetime.now(timezone.utc)
    project.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)
    return _read_project(project)


@router.get("/research/{research_id}/status", response_model=ResearchStatusRead)
def get_research_status(
    research_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ResearchStatusRead:
    project = db.query(ResearchProject).filter(ResearchProject.id == research_id).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    return ResearchStatusRead(
        research_id=project.id,
        status=project.status,
        current_stage=project.current_stage,
        updated_at=project.updated_at,
    )


@router.post("/research/{research_id}/cancel", response_model=ResearchStatusRead)
def cancel_research_project(
    research_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ResearchStatusRead:
    project = db.query(ResearchProject).filter(ResearchProject.id == research_id).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    project.status = ResearchStatus.CANCELLED.value
    project.current_stage = ResearchStatus.CANCELLED.value
    project.updated_at = datetime.now(timezone.utc)
    db.commit()
    return ResearchStatusRead(
        research_id=project.id,
        status=project.status,
        current_stage=project.current_stage,
        updated_at=project.updated_at,
    )


@router.get("/research/{research_id}/report", response_model=ResearchReportRead | None)
def get_research_report(
    research_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ResearchReportRead | None:
    project = db.query(ResearchProject).filter(ResearchProject.id == research_id).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    report = db.query(ResearchReport).filter(ResearchReport.research_id == research_id).first()
    return _build_report_read(report)


@router.get("/research/{research_id}/sources", response_model=list[ResearchSourceRead])
def list_research_sources(
    research_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[ResearchSourceRead]:
    project = db.query(ResearchProject).filter(ResearchProject.id == research_id).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    sources = db.query(ResearchSource).filter(ResearchSource.research_id == research_id).order_by(ResearchSource.created_at.desc()).all()
    return [_build_source_read(source) for source in sources]


@router.get("/research/{research_id}/findings", response_model=list[ResearchFindingRead])
def list_research_findings(
    research_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[ResearchFindingRead]:
    project = db.query(ResearchProject).filter(ResearchProject.id == research_id).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    findings = db.query(ResearchFinding).filter(ResearchFinding.research_id == research_id).order_by(ResearchFinding.created_at.desc()).all()
    return [_build_finding_read(finding) for finding in findings]


@router.get("/research/{research_id}/export", response_model=ResearchExportRead)
def export_research_project(
    research_id: UUID,
    fmt: str = Query(default="markdown", alias="format"),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ResearchExportRead:
    project = db.query(ResearchProject).filter(ResearchProject.id == research_id).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    report = db.query(ResearchReport).filter(ResearchReport.research_id == research_id).first()
    service = ResearchEngineService(db)
    if fmt.lower() == "markdown":
        content = service.export_markdown(project, report)
    else:
        content = service.export_markdown(project, report)
    return ResearchExportRead(format=fmt.lower(), content=content)


@router.get("/workspaces/{workspace_id}/research", response_model=list[ResearchProjectRead])
def list_workspace_research_projects(
    workspace_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[ResearchProjectRead]:
    _workspace_membership(db, current_user, workspace_id)
    projects = (
        db.query(ResearchProject)
        .filter(ResearchProject.workspace_id == workspace_id)
        .order_by(ResearchProject.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_read_project(project) for project in projects]
