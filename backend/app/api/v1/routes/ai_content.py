from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import get_current_user
from app.db.session import get_db
from app.models import User, WorkspaceMembership
from app.schemas.ai_content import CritiqueRequest, FactCheckRequest, IdeaRequest, IdeaResponse, WritingRequest, WritingResponse
from app.services.ai_content import (
    BrandConsistencyService,
    ContentScoringService,
    CritiqueService,
    FactCheckService,
    HashtagService,
    HookGenerationService,
    IdeationService,
    RepurposingService,
    RewritingService,
    WritingAssistantService,
)

router = APIRouter(tags=["ai content intelligence"])


def _workspace_membership(db: DBSession, user: User, workspace_id: UUID) -> WorkspaceMembership:
    membership = (
        db.query(WorkspaceMembership)
        .filter(WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.user_id == user.id)
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    return membership


@router.post("/content/intelligence", response_model=IdeaResponse)
@router.post("/content/intelligence/ideas", response_model=IdeaResponse)
@router.post("/content/intelligence/ideate", response_model=IdeaResponse)
@router.post("/workspaces/{workspace_id}/content/intelligence/ideas", response_model=IdeaResponse)
def generate_ideas(
    payload: IdeaRequest,
    workspace_id: UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> IdeaResponse:
    brand_context = payload.brand or {}
    target_workspace_id = workspace_id or (payload.workspace_id and UUID(str(payload.workspace_id))) or (brand_context.get("workspace_id") and UUID(str(brand_context.get("workspace_id"))))
    if target_workspace_id is None:
        raise HTTPException(status_code=422, detail="workspace_id is required.")
    _workspace_membership(db, current_user, target_workspace_id)
    service = IdeationService(db, target_workspace_id)
    brand = brand_context or {"name": "Your brand", "voice": "Professional and clear", "audience": "Target audience", "pillar": "Brand storytelling"}
    research = payload.research or {"references": []}
    result = service.generate({
        "topic": payload.topic,
        "objective": payload.objective,
        "platform": payload.platform,
        "language": payload.language,
        "content_type": payload.content_type,
    }, brand=brand, research=research)
    return IdeaResponse.model_validate(result)


@router.post("/content/intelligence/writing", response_model=WritingResponse)
@router.post("/content/intelligence/write", response_model=WritingResponse)
@router.post("/workspaces/{workspace_id}/content/intelligence/writing", response_model=WritingResponse)
def writing_assistant(
    payload: WritingRequest,
    workspace_id: UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> WritingResponse:
    brand_context = payload.brand or {}
    target_workspace_id = workspace_id or (payload.workspace_id and UUID(str(payload.workspace_id))) or (brand_context.get("workspace_id") and UUID(str(brand_context.get("workspace_id"))))
    if target_workspace_id is None:
        raise HTTPException(status_code=422, detail="workspace_id is required.")
    _workspace_membership(db, current_user, target_workspace_id)
    service = WritingAssistantService(db, target_workspace_id)
    result = service.improve({
        "text": payload.text,
        "action": payload.action,
        "platform": payload.platform,
        "tone": payload.tone,
        "objective": payload.objective,
    }, brand=brand_context)
    return WritingResponse.model_validate(result)


@router.post("/content/intelligence/critique")
@router.post("/workspaces/{workspace_id}/content/intelligence/critique")
def critique_content(
    payload: CritiqueRequest,
    workspace_id: UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, object]:
    brand_context = payload.brand or {}
    target_workspace_id = workspace_id or (payload.workspace_id and UUID(str(payload.workspace_id))) or (brand_context.get("workspace_id") and UUID(str(brand_context.get("workspace_id"))))
    if target_workspace_id is None:
        raise HTTPException(status_code=422, detail="workspace_id is required.")
    _workspace_membership(db, current_user, target_workspace_id)
    service = CritiqueService(db, target_workspace_id)
    return service.critique({"text": payload.text}, brand=brand_context)


@router.post("/content/intelligence/fact-check")
@router.post("/workspaces/{workspace_id}/content/intelligence/fact-check")
def fact_check_content(
    payload: FactCheckRequest,
    workspace_id: UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, object]:
    research_context = payload.research or {}
    target_workspace_id = workspace_id or (payload.workspace_id and UUID(str(payload.workspace_id))) or (research_context.get("workspace_id") and UUID(str(research_context.get("workspace_id"))))
    if target_workspace_id is None:
        raise HTTPException(status_code=422, detail="workspace_id is required.")
    _workspace_membership(db, current_user, target_workspace_id)
    service = FactCheckService(db, target_workspace_id)
    return service.fact_check({"claims": payload.claims}, research=research_context)


@router.post("/content/intelligence/hooks")
def generate_hooks(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, object]:
    workspace_id = payload.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=422, detail="workspace_id is required.")
    _workspace_membership(db, current_user, UUID(str(workspace_id)))
    return HookGenerationService(db, workspace_id).generate(payload.get("topic") or "brand growth", objective=payload.get("objective"))


@router.post("/content/intelligence/hashtags")
def recommend_hashtags(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, object]:
    workspace_id = payload.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=422, detail="workspace_id is required.")
    _workspace_membership(db, current_user, UUID(str(workspace_id)))
    return HashtagService(db, workspace_id).recommend(payload.get("topic") or "brand growth", platform=payload.get("platform") or "instagram")


@router.post("/content/intelligence/repurpose")
def repurpose_content(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, object]:
    workspace_id = payload.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=422, detail="workspace_id is required.")
    _workspace_membership(db, current_user, UUID(str(workspace_id)))
    return RepurposingService(db, workspace_id).repurpose(payload.get("text") or "", platform=payload.get("platform") or "instagram")


@router.post("/content/intelligence/brand-consistency")
def brand_consistency_check(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, object]:
    workspace_id = payload.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=422, detail="workspace_id is required.")
    _workspace_membership(db, current_user, UUID(str(workspace_id)))
    return BrandConsistencyService(db, workspace_id).assess(payload.get("text") or "", brand=payload.get("brand") or {})


@router.post("/content/intelligence/score")
def score_content(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, object]:
    workspace_id = payload.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=422, detail="workspace_id is required.")
    _workspace_membership(db, current_user, UUID(str(workspace_id)))
    return ContentScoringService(db, workspace_id).score(payload.get("text") or "", objective=payload.get("objective"))


@router.post("/content/intelligence/rewrite")
def rewrite_content(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, object]:
    workspace_id = payload.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=422, detail="workspace_id is required.")
    _workspace_membership(db, current_user, UUID(str(workspace_id)))
    return RewritingService(db, workspace_id).rewrite_text(payload.get("text") or "", tone=payload.get("tone") or "professional")
