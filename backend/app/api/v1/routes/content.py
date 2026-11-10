from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import get_current_user
from app.db.session import get_db
from app.models import (
    Brand,
    ContentApproval,
    ContentDraft,
    ContentProject,
    ContentVersion,
    ResearchProject,
    ResearchReport,
    User,
    WorkspaceMembership,
)
from app.schemas.content import (
    ContentApprovalDecision,
    ContentApprovalRead,
    ContentApprovalSubmit,
    ContentDraftCreate,
    ContentDraftRead,
    ContentDraftUpdate,
    ContentProjectCreate,
    ContentProjectRead,
    ContentProjectUpdate,
    DraftVersionRead,
    PlatformValidationRead,
)
from app.services.content_studio import ContentStudioService, ContentValidationError

router = APIRouter(tags=["content studio"])


def _workspace_membership(db: DBSession, user: User, workspace_id: UUID) -> WorkspaceMembership:
    membership = (
        db.query(WorkspaceMembership)
        .filter(WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.user_id == user.id)
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    return membership


def _project_read(project: ContentProject) -> ContentProjectRead:
    return ContentProjectRead.model_validate(project)


def _validate_project_references(
    db: DBSession,
    workspace_id: UUID,
    brand_id: UUID | None,
    research_report_id: UUID | None,
) -> None:
    if brand_id is not None:
        brand = db.query(Brand).filter(Brand.id == brand_id, Brand.workspace_id == workspace_id).first()
        if brand is None:
            raise HTTPException(status_code=404, detail="Brand not found in this workspace.")
    if research_report_id is not None:
        report = (
            db.query(ResearchReport)
            .join(ResearchProject, ResearchProject.id == ResearchReport.research_id)
            .filter(
                ResearchReport.id == research_report_id,
                ResearchProject.workspace_id == workspace_id,
            )
            .first()
        )
        if report is None:
            raise HTTPException(status_code=404, detail="Research report not found in this workspace.")


def _ensure_project_editable(project: ContentProject) -> None:
    if project.status in {"ready_for_review", "in_review", "archived"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This content project cannot be edited in its current state.",
        )


def _mark_project_revised(project: ContentProject) -> None:
    if project.status in {"approved", "rejected"}:
        project.status = "draft"
        project.approved_at = None
    for draft in project.drafts:
        draft.status = "draft"


def _approval_read(approval: ContentApproval) -> ContentApprovalRead:
    return ContentApprovalRead.model_validate(approval)


def _draft_read(draft: ContentDraft) -> ContentDraftRead:
    versions = [
        {
            "id": version.id,
            "draft_id": version.draft_id,
            "version_number": version.version_number,
            "platform": version.platform,
            "title": version.title,
            "hook": version.hook,
            "body": version.body,
            "cta": version.cta,
            "hashtags": version.hashtags or [],
            "snapshot": version.snapshot,
            "change_reason": version.change_reason,
            "created_by": version.created_by,
            "created_at": version.created_at,
        }
        for version in sorted(draft.versions, key=lambda item: item.version_number)
    ]
    return ContentDraftRead(
        id=draft.id,
        project_id=draft.project_id,
        platform=draft.platform,
        title=draft.title,
        hook=draft.hook,
        body=draft.body,
        cta=draft.cta,
        hashtags=draft.hashtags or [],
        media_asset_ids=list(draft.media_asset_ids or []),
        status=draft.status,
        ai_generated=draft.ai_generated,
        version_count=draft.version_count,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        versions=versions,
    )


@router.post("/content/projects", response_model=ContentProjectRead, status_code=status.HTTP_201_CREATED)
def create_content_project(
    payload: ContentProjectCreate,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ContentProjectRead:
    _workspace_membership(db, current_user, payload.workspace_id)
    _validate_project_references(
        db, payload.workspace_id, payload.brand_id, payload.research_report_id
    )
    project = ContentProject(
        workspace_id=payload.workspace_id,
        brand_id=payload.brand_id,
        created_by=current_user.id,
        title=payload.title,
        topic=payload.topic,
        objective=payload.objective,
        content_type=str(payload.content_type),
        selected_platforms=[str(platform) for platform in payload.selected_platforms],
        content_pillar=payload.content_pillar,
        target_audience=payload.target_audience,
        preferred_tone=payload.preferred_tone,
        language=payload.language,
        keywords=payload.keywords,
        required_phrases=payload.required_phrases,
        prohibited_phrases=payload.prohibited_phrases,
        cta_requirements=payload.cta_requirements,
        hashtag_preferences=payload.hashtag_preferences,
        emoji_preferences=payload.emoji_preferences,
        desired_length=payload.desired_length,
        research_report_id=payload.research_report_id,
        status="draft",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return _project_read(project)


@router.get("/content/projects", response_model=list[ContentProjectRead])
def list_content_projects(
    workspace_id: UUID | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[ContentProjectRead]:
    if workspace_id is not None:
        _workspace_membership(db, current_user, workspace_id)
        projects = db.query(ContentProject).filter(ContentProject.workspace_id == workspace_id).order_by(ContentProject.created_at.desc()).all()
        return [_project_read(project) for project in projects]
    workspace_ids = [row.workspace_id for row in db.query(WorkspaceMembership.workspace_id).filter(WorkspaceMembership.user_id == current_user.id).all()]
    if not workspace_ids:
        return []
    projects = db.query(ContentProject).filter(ContentProject.workspace_id.in_(workspace_ids)).order_by(ContentProject.created_at.desc()).all()
    return [_project_read(project) for project in projects]


@router.get("/content/projects/{project_id}", response_model=ContentProjectRead)
def get_content_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ContentProjectRead:
    project = db.query(ContentProject).filter(ContentProject.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Content project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    return _project_read(project)


@router.patch("/content/projects/{project_id}", response_model=ContentProjectRead)
def update_content_project(
    project_id: UUID,
    payload: ContentProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ContentProjectRead:
    project = db.query(ContentProject).filter(ContentProject.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Content project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    _ensure_project_editable(project)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field is required.")
    _validate_project_references(
        db,
        project.workspace_id,
        changes.get("brand_id", project.brand_id),
        changes.get("research_report_id", project.research_report_id),
    )
    for required_field in (
        "title",
        "content_type",
        "selected_platforms",
        "language",
        "keywords",
        "required_phrases",
        "prohibited_phrases",
    ):
        if required_field in changes and changes[required_field] is None:
            raise HTTPException(
                status_code=422,
                detail=f"{required_field} cannot be null.",
            )
    for field, value in changes.items():
        if field == "selected_platforms" and value is not None:
            if not value:
                raise HTTPException(status_code=422, detail="Select at least one platform.")
            platforms = [str(platform) for platform in value]
            if any(draft.platform not in platforms for draft in project.drafts):
                raise HTTPException(
                    status_code=409,
                    detail="A selected platform cannot be removed while it has a draft.",
                )
            setattr(project, field, platforms)
        elif field == "content_type" and value is not None:
            setattr(project, field, str(value))
        else:
            setattr(project, field, value)
    _mark_project_revised(project)
    project.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)
    return _project_read(project)


@router.post("/content/projects/{project_id}/generate", response_model=ContentDraftRead)
def generate_content_draft(
    project_id: UUID,
    platform: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ContentDraftRead:
    project = db.query(ContentProject).filter(ContentProject.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Content project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    _ensure_project_editable(project)
    service = ContentStudioService(db)
    selected_platform = platform or (project.selected_platforms[0] if project.selected_platforms else "instagram")
    if selected_platform not in project.selected_platforms:
        raise HTTPException(status_code=400, detail="The requested platform is not selected for this content project.")
    try:
        generated = service.generate_for_project(project, platform=selected_platform)
    except ContentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    draft = next(
        (item for item in project.drafts if item.platform == selected_platform),
        None,
    )
    if draft is None or draft.platform != selected_platform:
        draft = service.create_draft(project, platform=selected_platform)
    draft.title = generated.title
    draft.hook = generated.hook
    draft.body = generated.body
    draft.cta = generated.cta
    draft.hashtags = generated.hashtags
    draft.ai_generated = True
    _mark_project_revised(project)
    service.create_version(draft, change_reason="AI-generated draft", created_by=current_user.id)
    db.commit()
    db.refresh(draft)
    return _draft_read(draft)


@router.post(
    "/content/projects/{project_id}/drafts",
    response_model=ContentDraftRead,
    status_code=status.HTTP_201_CREATED,
)
def create_draft(
    project_id: UUID,
    payload: ContentDraftCreate,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ContentDraftRead:
    project = db.query(ContentProject).filter(ContentProject.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Content project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    _ensure_project_editable(project)
    selected_platform = str(payload.platform)
    if selected_platform not in project.selected_platforms:
        raise HTTPException(status_code=400, detail="The requested platform is not selected for this content project.")
    if any(draft.platform == selected_platform for draft in project.drafts):
        raise HTTPException(status_code=409, detail="A draft already exists for this platform.")
    service = ContentStudioService(db)
    draft = service.create_draft(project, platform=selected_platform)
    draft.title = payload.title or ""
    draft.hook = payload.hook or ""
    draft.body = payload.body or ""
    draft.cta = payload.cta or ""
    draft.hashtags = payload.hashtags or []
    draft.ai_generated = payload.ai_generated
    if draft.body or draft.hook or draft.title or draft.cta or draft.hashtags:
        service.create_version(draft, change_reason="Manual draft saved", created_by=current_user.id)
    db.commit()
    db.refresh(draft)
    return _draft_read(draft)


@router.get("/content/projects/{project_id}/drafts", response_model=list[ContentDraftRead])
def list_content_drafts(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[ContentDraftRead]:
    project = db.query(ContentProject).filter(ContentProject.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Content project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    drafts = db.query(ContentDraft).filter(ContentDraft.project_id == project_id).order_by(ContentDraft.created_at.desc()).all()
    return [_draft_read(draft) for draft in drafts]


@router.post(
    "/content/projects/{project_id}/drafts/{draft_id}/validate",
    response_model=PlatformValidationRead,
)
def validate_content_draft(
    project_id: UUID,
    draft_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> PlatformValidationRead:
    draft = db.query(ContentDraft).filter(
        ContentDraft.id == draft_id,
        ContentDraft.project_id == project_id,
    ).first()
    if draft is None:
        raise HTTPException(status_code=404, detail="Content draft not found.")
    _workspace_membership(db, current_user, draft.project.workspace_id)
    result = ContentStudioService(db).platform_validation(
        draft.platform,
        {
            "title": draft.title,
            "hook": draft.hook,
            "body": draft.body,
            "cta": draft.cta,
            "hashtags": draft.hashtags,
        },
    )
    return PlatformValidationRead(**result)


@router.patch("/content/projects/{project_id}/drafts/{draft_id}", response_model=ContentDraftRead)
def update_content_draft(
    project_id: UUID,
    draft_id: UUID,
    payload: ContentDraftUpdate,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ContentDraftRead:
    draft = db.query(ContentDraft).filter(ContentDraft.id == draft_id, ContentDraft.project_id == project_id).first()
    if draft is None:
        raise HTTPException(status_code=404, detail="Content draft not found.")
    _workspace_membership(db, current_user, draft.project.workspace_id)
    _ensure_project_editable(draft.project)
    before = {"title": draft.title, "hook": draft.hook, "body": draft.body, "cta": draft.cta, "hashtags": list(draft.hashtags or [])}
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field is required.")
    for field, value in changes.items():
        setattr(draft, field, value)
    if before != {"title": draft.title, "hook": draft.hook, "body": draft.body, "cta": draft.cta, "hashtags": list(draft.hashtags or [])}:
        service = ContentStudioService(db)
        service.create_version(draft, change_reason="Manual revision saved", created_by=current_user.id)
        _mark_project_revised(draft.project)
    draft.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(draft)
    return _draft_read(draft)


@router.get(
    "/content/projects/{project_id}/drafts/{draft_id}/versions",
    response_model=list[DraftVersionRead],
)
def list_content_draft_versions(
    project_id: UUID,
    draft_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[DraftVersionRead]:
    draft = db.query(ContentDraft).filter(
        ContentDraft.id == draft_id,
        ContentDraft.project_id == project_id,
    ).first()
    if draft is None:
        raise HTTPException(status_code=404, detail="Content draft not found.")
    _workspace_membership(db, current_user, draft.project.workspace_id)
    versions = (
        db.query(ContentVersion)
        .filter(ContentVersion.draft_id == draft_id)
        .order_by(ContentVersion.version_number.asc())
        .all()
    )
    return [DraftVersionRead.model_validate(version) for version in versions]


@router.post(
    "/content/projects/{project_id}/drafts/{draft_id}/versions/{version_id}/restore",
    response_model=ContentDraftRead,
)
def restore_content_draft_version(
    project_id: UUID,
    draft_id: UUID,
    version_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ContentDraftRead:
    draft = db.query(ContentDraft).filter(
        ContentDraft.id == draft_id,
        ContentDraft.project_id == project_id,
    ).first()
    if draft is None:
        raise HTTPException(status_code=404, detail="Content draft not found.")
    _workspace_membership(db, current_user, draft.project.workspace_id)
    _ensure_project_editable(draft.project)
    version = db.query(ContentVersion).filter(
        ContentVersion.id == version_id,
        ContentVersion.draft_id == draft_id,
    ).first()
    if version is None:
        raise HTTPException(status_code=404, detail="Content draft version not found.")
    draft.title = version.title
    draft.hook = version.hook
    draft.body = version.body
    draft.cta = version.cta
    draft.hashtags = list(version.hashtags or [])
    if isinstance(version.snapshot, dict) and isinstance(version.snapshot.get("media_asset_ids"), list):
        draft.media_asset_ids = [str(item) for item in version.snapshot["media_asset_ids"]]
    _mark_project_revised(draft.project)
    ContentStudioService(db).create_version(
        draft,
        change_reason=f"Restored version {version.version_number}",
        created_by=current_user.id,
    )
    db.commit()
    db.refresh(draft)
    return _draft_read(draft)


@router.post("/content/projects/{project_id}/submit-for-approval", response_model=ContentApprovalRead)
def submit_for_approval(
    project_id: UUID,
    payload: ContentApprovalSubmit | None = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ContentApprovalRead:
    project = db.query(ContentProject).filter(ContentProject.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Content project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    _ensure_project_editable(project)
    if project.status == "approved":
        raise HTTPException(status_code=409, detail="Edit a draft before requesting approval again.")
    drafts = db.query(ContentDraft).filter(ContentDraft.project_id == project_id).all()
    if not drafts:
        raise HTTPException(status_code=400, detail="Create at least one draft before requesting approval.")
    service = ContentStudioService(db)
    invalid_drafts = []
    for draft in drafts:
        validation = service.platform_validation(
            draft.platform,
            {
                "title": draft.title,
                "hook": draft.hook,
                "body": draft.body,
                "cta": draft.cta,
                "hashtags": draft.hashtags,
            },
        )
        if not validation["valid"]:
            invalid_drafts.append(
                f"{draft.platform}: {'; '.join(validation['errors'])}"
            )
    if invalid_drafts:
        raise HTTPException(
            status_code=400,
            detail=f"Fix platform validation errors before requesting approval: {' | '.join(invalid_drafts)}",
        )
    existing_pending = (
        db.query(ContentApproval)
        .filter(ContentApproval.project_id == project_id, ContentApproval.status == "pending")
        .first()
    )
    if existing_pending is not None:
        raise HTTPException(status_code=409, detail="This project already has a pending approval request.")
    project.status = "ready_for_review"
    project.submitted_at = datetime.now(timezone.utc)
    for draft in drafts:
        draft.status = "ready_for_review"
    approval = ContentApproval(
        project_id=project.id,
        status="pending",
        comments=payload.comments if payload else None,
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return _approval_read(approval)


@router.post("/content/projects/{project_id}/approvals/{approval_id}/decision", response_model=ContentApprovalRead)
def decide_content_approval(
    project_id: UUID,
    approval_id: UUID,
    payload: ContentApprovalDecision,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ContentApprovalRead:
    project = db.query(ContentProject).filter(ContentProject.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Content project not found.")
    approval = (
        db.query(ContentApproval)
        .filter(
            ContentApproval.id == approval_id,
            ContentApproval.project_id == project_id,
        )
        .with_for_update()
        .first()
    )
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval record not found.")
    membership = _workspace_membership(db, current_user, project.workspace_id)
    if membership.role not in {"OWNER", "ADMIN"}:
        raise HTTPException(status_code=403, detail="Only workspace Owners and Admins can decide approvals.")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="This approval request has already been decided.")
    decision = str(payload.status)
    approval.status = decision
    approval.comments = payload.comments
    approval.reviewed_by = current_user.id
    approval.updated_at = datetime.now(timezone.utc)
    status_by_decision = {
        "approved": "approved",
        "rejected": "rejected",
        "changes_requested": "draft",
    }
    project.status = status_by_decision[decision]
    project.approved_at = datetime.now(timezone.utc) if decision == "approved" else None
    draft_status = status_by_decision[decision]
    for draft in project.drafts:
        draft.status = draft_status
    db.commit()
    db.refresh(approval)
    return _approval_read(approval)


@router.get("/content/projects/{project_id}/approvals", response_model=list[ContentApprovalRead])
def list_content_approvals(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[ContentApprovalRead]:
    project = db.query(ContentProject).filter(ContentProject.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Content project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    approvals = db.query(ContentApproval).filter(ContentApproval.project_id == project_id).order_by(ContentApproval.created_at.desc()).all()
    return [
        _approval_read(item)
        for item in approvals
    ]


@router.delete("/content/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_content_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    project = db.query(ContentProject).filter(ContentProject.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Content project not found.")
    _workspace_membership(db, current_user, project.workspace_id)
    db.delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
