from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import (
    get_current_user,
    require_workspace_admin,
    require_workspace_member,
)
from app.api.v1.dependencies.brands import (
    require_brand_admin,
    require_brand_member,
)
from app.db.session import get_db
from app.models import (
    Brand,
    BrandGoal,
    BrandPolicy,
    BrandVoice,
    ContentPillar,
    TargetAudience,
    User,
    WorkspaceMembership,
)
from app.schemas.brands import (
    APIModel,
    BrandContext,
    BrandCreate,
    BrandGoalInput,
    BrandGoalRead,
    BrandGoalUpdate,
    BrandOverview,
    BrandPolicyInput,
    BrandPolicyRead,
    BrandPolicyUpdate,
    BrandRead,
    BrandStatus,
    BrandUpdate,
    BrandVoiceInput,
    BrandVoiceRead,
    ContentPillarInput,
    ContentPillarRead,
    ContentPillarUpdate,
    TargetAudienceInput,
    TargetAudienceRead,
    TargetAudienceUpdate,
)
from app.services.audit import record_audit
from app.services.brand_context import brand_context_service
from app.services.identity import generate_workspace_slug

router = APIRouter(tags=["brands"])
ModelT = TypeVar("ModelT")


def _read(schema: type[ModelT], entity: Any) -> ModelT:
    return schema.model_validate(entity)


def _record_change(
    db: DBSession,
    *,
    action: str,
    brand: Brand,
    actor: User,
    resource_type: str,
    resource_id: UUID | str | None = None,
    fields: list[str] | None = None,
) -> None:
    record_audit(
        db,
        action=action,
        resource_type=resource_type,
        actor_user_id=actor.id,
        workspace_id=brand.workspace_id,
        resource_id=resource_id or brand.id,
        metadata={"fields": fields} if fields else {},
    )


def _apply_update(entity: Any, changes: dict[str, Any]) -> None:
    for field, value in changes.items():
        if field in {"website_url", "logo_url"} and value is not None:
            value = str(value)
        column = entity.__table__.columns.get(field)
        if column is None:
            raise ValueError(f"Unsupported field: {field}")
        if value is None and not column.nullable:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} cannot be null.",
            )
        setattr(entity, field, value)


def _paginate(query, offset: int, limit: int):
    return query.offset(offset).limit(limit).all()


@router.post(
    "/workspaces/{workspace_id}/brands",
    response_model=BrandRead,
    status_code=status.HTTP_201_CREATED,
)
def create_brand(
    workspace_id: UUID,
    payload: BrandCreate,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> BrandRead:
    brand = Brand(
        workspace_id=workspace_id,
        name=payload.name,
        slug=payload.slug or generate_workspace_slug(payload.name),
        description=payload.description,
        website_url=str(payload.website_url) if payload.website_url else None,
        industry=payload.industry,
        business_type=payload.business_type,
        logo_url=str(payload.logo_url) if payload.logo_url else None,
        primary_color=payload.primary_color,
        secondary_color=payload.secondary_color,
        status=BrandStatus.ACTIVE.value,
        created_by=current_user.id,
    )
    db.add(brand)
    try:
        db.flush()
        _record_change(
            db,
            action="brand.created",
            brand=brand,
            actor=current_user,
            resource_type="brand",
            resource_id=brand.id,
        )
        db.commit()
        db.refresh(brand)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A brand with this slug already exists in the workspace.",
        ) from exc
    return _read(BrandRead, brand)


@router.get("/workspaces/{workspace_id}/brands", response_model=list[BrandRead])
def list_brands(
    workspace_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> list[BrandRead]:
    brands = _paginate(
        db.query(Brand)
        .filter(Brand.workspace_id == workspace_id)
        .order_by(Brand.updated_at.desc()),
        offset,
        limit,
    )
    return [_read(BrandRead, brand) for brand in brands]


@router.get("/brands/{brand_id}", response_model=BrandRead)
def read_brand(brand: Brand = Depends(require_brand_member)) -> BrandRead:
    return _read(BrandRead, brand)


@router.patch("/brands/{brand_id}", response_model=BrandRead)
def update_brand(
    payload: BrandUpdate,
    brand: Brand = Depends(require_brand_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> BrandRead:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field is required.")
    _apply_update(brand, changes)
    _record_change(
        db,
        action="brand.updated",
        brand=brand,
        actor=current_user,
        resource_type="brand",
        fields=list(changes),
    )
    try:
        db.commit()
        db.refresh(brand)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A brand with this slug already exists in the workspace.",
        ) from exc
    return _read(BrandRead, brand)


@router.delete("/brands/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_brand(
    brand: Brand = Depends(require_brand_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    brand.status = BrandStatus.ARCHIVED.value
    _record_change(
        db,
        action="brand.archived",
        brand=brand,
        actor=current_user,
        resource_type="brand",
        resource_id=brand.id,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/brands/{brand_id}/overview", response_model=BrandOverview)
def brand_overview(
    brand: Brand = Depends(require_brand_member),
    db: DBSession = Depends(get_db),
) -> BrandOverview:
    db.refresh(brand)
    return BrandOverview(
        brand=_read(BrandRead, brand),
        voice=_read(BrandVoiceRead, brand.voice) if brand.voice else None,
        audiences=[_read(TargetAudienceRead, row) for row in brand.audiences],
        pillars=[_read(ContentPillarRead, row) for row in brand.pillars],
        goals=[_read(BrandGoalRead, row) for row in brand.goals],
        policies=[_read(BrandPolicyRead, row) for row in brand.policies],
    )


@router.get("/brands/{brand_id}/context", response_model=BrandContext)
def brand_context(
    brand: Brand = Depends(require_brand_member),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> BrandContext:
    return brand_context_service.get_brand_context(
        brand.id, brand.workspace_id, current_user, db
    )


@router.get("/brands/{brand_id}/voice", response_model=BrandVoiceRead | None)
def get_brand_voice(
    brand: Brand = Depends(require_brand_member),
) -> BrandVoiceRead | None:
    return _read(BrandVoiceRead, brand.voice) if brand.voice else None


@router.put("/brands/{brand_id}/voice", response_model=BrandVoiceRead)
def put_brand_voice(
    payload: BrandVoiceInput,
    brand: Brand = Depends(require_brand_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> BrandVoiceRead:
    voice = brand.voice
    if voice is None:
        voice = BrandVoice(brand_id=brand.id)
        db.add(voice)
    _apply_update(voice, payload.model_dump())
    db.flush()
    _record_change(
        db,
        action="brand.voice_updated",
        brand=brand,
        actor=current_user,
        resource_type="brand_voice",
        resource_id=voice.id,
    )
    db.commit()
    db.refresh(voice)
    return _read(BrandVoiceRead, voice)


def _list_children(
    brand_id: UUID,
    entity: type[Any],
    schema: type[Any],
    offset: int,
    limit: int,
    brand: Brand,
    db: DBSession,
) -> list[Any]:
    rows = _paginate(
        db.query(entity).filter(entity.brand_id == brand_id).order_by(entity.created_at.desc()),
        offset,
        limit,
    )
    return [_read(schema, row) for row in rows]


def _create_child(
    *,
    brand: Brand,
    actor: User,
    db: DBSession,
    entity: type[Any],
    schema: type[Any],
    payload: APIModel,
    action: str,
) -> Any:
    values = payload.model_dump()
    if "goal_type" in values and values["goal_type"] is not None:
        values["goal_type"] = str(values["goal_type"])
    if "policy_type" in values and values["policy_type"] is not None:
        values["policy_type"] = str(values["policy_type"])
    if "severity" in values and values["severity"] is not None:
        values["severity"] = str(values["severity"])
    row = entity(brand_id=brand.id, **values)
    db.add(row)
    db.flush()
    _record_change(
        db,
        action=action,
        brand=brand,
        actor=actor,
        resource_type=entity.__tablename__,
        resource_id=row.id,
    )
    db.commit()
    db.refresh(row)
    return _read(schema, row)


def _get_child(
    *,
    entity: type[Any],
    resource_id: UUID,
    brand: Brand,
    db: DBSession,
) -> Any:
    row = (
        db.query(entity)
        .filter(entity.id == resource_id, entity.brand_id == brand.id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Brand resource not found.")
    return row


def _update_child(
    *,
    row: Any,
    payload: Any,
    brand: Brand,
    actor: User,
    db: DBSession,
    action: str,
    resource_type: str,
    schema: type[Any],
) -> Any:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field is required.")
    _apply_update(row, changes)
    _record_change(
        db,
        action=action,
        brand=brand,
        actor=actor,
        resource_type=resource_type,
        resource_id=row.id,
        fields=list(changes),
    )
    db.commit()
    db.refresh(row)
    return _read(schema, row)


def _delete_child(
    *,
    row: Any,
    brand: Brand,
    actor: User,
    db: DBSession,
    action: str,
    resource_type: str,
) -> Response:
    resource_id = row.id
    _record_change(
        db,
        action=action,
        brand=brand,
        actor=actor,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/brands/{brand_id}/audiences", response_model=list[TargetAudienceRead])
def list_audiences(
    brand: Brand = Depends(require_brand_member),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: DBSession = Depends(get_db),
) -> list[TargetAudienceRead]:
    return _list_children(brand.id, TargetAudience, TargetAudienceRead, offset, limit, brand, db)


@router.post("/brands/{brand_id}/audiences", response_model=TargetAudienceRead, status_code=201)
def create_audience(
    payload: TargetAudienceInput,
    brand: Brand = Depends(require_brand_admin),
    actor: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> TargetAudienceRead:
    return _create_child(
        brand=brand, actor=actor, db=db, entity=TargetAudience,
        schema=TargetAudienceRead, payload=payload, action="brand.audience_created"
    )


@router.get("/brands/{brand_id}/audiences/{audience_id}", response_model=TargetAudienceRead)
def get_audience(
    audience_id: UUID,
    brand: Brand = Depends(require_brand_member),
    db: DBSession = Depends(get_db),
) -> TargetAudienceRead:
    return _read(TargetAudienceRead, _get_child(entity=TargetAudience, resource_id=audience_id, brand=brand, db=db))


@router.patch("/brands/{brand_id}/audiences/{audience_id}", response_model=TargetAudienceRead)
def update_audience(
    audience_id: UUID,
    payload: TargetAudienceUpdate,
    brand: Brand = Depends(require_brand_admin),
    actor: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> TargetAudienceRead:
    row = _get_child(entity=TargetAudience, resource_id=audience_id, brand=brand, db=db)
    return _update_child(row=row, payload=payload, brand=brand, actor=actor, db=db, action="brand.audience_updated", resource_type="target_audience", schema=TargetAudienceRead)


@router.delete("/brands/{brand_id}/audiences/{audience_id}", status_code=204)
def delete_audience(
    audience_id: UUID,
    brand: Brand = Depends(require_brand_admin),
    actor: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    row = _get_child(entity=TargetAudience, resource_id=audience_id, brand=brand, db=db)
    return _delete_child(row=row, brand=brand, actor=actor, db=db, action="brand.audience_deleted", resource_type="target_audience")


@router.get("/brands/{brand_id}/pillars", response_model=list[ContentPillarRead])
def list_pillars(
    brand: Brand = Depends(require_brand_member),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: DBSession = Depends(get_db),
) -> list[ContentPillarRead]:
    return _list_children(brand.id, ContentPillar, ContentPillarRead, offset, limit, brand, db)


@router.post("/brands/{brand_id}/pillars", response_model=ContentPillarRead, status_code=201)
def create_pillar(
    payload: ContentPillarInput,
    brand: Brand = Depends(require_brand_admin),
    actor: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ContentPillarRead:
    return _create_child(brand=brand, actor=actor, db=db, entity=ContentPillar, schema=ContentPillarRead, payload=payload, action="brand.pillar_created")


@router.get("/brands/{brand_id}/pillars/{pillar_id}", response_model=ContentPillarRead)
def get_pillar(
    pillar_id: UUID,
    brand: Brand = Depends(require_brand_member),
    db: DBSession = Depends(get_db),
) -> ContentPillarRead:
    return _read(ContentPillarRead, _get_child(entity=ContentPillar, resource_id=pillar_id, brand=brand, db=db))


@router.patch("/brands/{brand_id}/pillars/{pillar_id}", response_model=ContentPillarRead)
def update_pillar(
    pillar_id: UUID,
    payload: ContentPillarUpdate,
    brand: Brand = Depends(require_brand_admin),
    actor: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ContentPillarRead:
    row = _get_child(entity=ContentPillar, resource_id=pillar_id, brand=brand, db=db)
    return _update_child(row=row, payload=payload, brand=brand, actor=actor, db=db, action="brand.pillar_updated", resource_type="content_pillar", schema=ContentPillarRead)


@router.delete("/brands/{brand_id}/pillars/{pillar_id}", status_code=204)
def delete_pillar(
    pillar_id: UUID,
    brand: Brand = Depends(require_brand_admin),
    actor: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    row = _get_child(entity=ContentPillar, resource_id=pillar_id, brand=brand, db=db)
    return _delete_child(row=row, brand=brand, actor=actor, db=db, action="brand.pillar_deleted", resource_type="content_pillar")


@router.get("/brands/{brand_id}/goals", response_model=list[BrandGoalRead])
def list_goals(
    brand: Brand = Depends(require_brand_member),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: DBSession = Depends(get_db),
) -> list[BrandGoalRead]:
    return _list_children(brand.id, BrandGoal, BrandGoalRead, offset, limit, brand, db)


@router.post("/brands/{brand_id}/goals", response_model=BrandGoalRead, status_code=201)
def create_goal(
    payload: BrandGoalInput,
    brand: Brand = Depends(require_brand_admin),
    actor: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> BrandGoalRead:
    return _create_child(brand=brand, actor=actor, db=db, entity=BrandGoal, schema=BrandGoalRead, payload=payload, action="brand.goal_created")


@router.get("/brands/{brand_id}/goals/{goal_id}", response_model=BrandGoalRead)
def get_goal(
    goal_id: UUID,
    brand: Brand = Depends(require_brand_member),
    db: DBSession = Depends(get_db),
) -> BrandGoalRead:
    return _read(BrandGoalRead, _get_child(entity=BrandGoal, resource_id=goal_id, brand=brand, db=db))


@router.patch("/brands/{brand_id}/goals/{goal_id}", response_model=BrandGoalRead)
def update_goal(
    goal_id: UUID,
    payload: BrandGoalUpdate,
    brand: Brand = Depends(require_brand_admin),
    actor: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> BrandGoalRead:
    row = _get_child(entity=BrandGoal, resource_id=goal_id, brand=brand, db=db)
    return _update_child(row=row, payload=payload, brand=brand, actor=actor, db=db, action="brand.goal_updated", resource_type="brand_goal", schema=BrandGoalRead)


@router.delete("/brands/{brand_id}/goals/{goal_id}", status_code=204)
def delete_goal(
    goal_id: UUID,
    brand: Brand = Depends(require_brand_admin),
    actor: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    row = _get_child(entity=BrandGoal, resource_id=goal_id, brand=brand, db=db)
    return _delete_child(row=row, brand=brand, actor=actor, db=db, action="brand.goal_deleted", resource_type="brand_goal")


@router.get("/brands/{brand_id}/policies", response_model=list[BrandPolicyRead])
def list_policies(
    brand: Brand = Depends(require_brand_member),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: DBSession = Depends(get_db),
) -> list[BrandPolicyRead]:
    return _list_children(brand.id, BrandPolicy, BrandPolicyRead, offset, limit, brand, db)


@router.post("/brands/{brand_id}/policies", response_model=BrandPolicyRead, status_code=201)
def create_policy(
    payload: BrandPolicyInput,
    brand: Brand = Depends(require_brand_admin),
    actor: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> BrandPolicyRead:
    return _create_child(brand=brand, actor=actor, db=db, entity=BrandPolicy, schema=BrandPolicyRead, payload=payload, action="brand.policy_created")


@router.get("/brands/{brand_id}/policies/{policy_id}", response_model=BrandPolicyRead)
def get_policy(
    policy_id: UUID,
    brand: Brand = Depends(require_brand_member),
    db: DBSession = Depends(get_db),
) -> BrandPolicyRead:
    return _read(BrandPolicyRead, _get_child(entity=BrandPolicy, resource_id=policy_id, brand=brand, db=db))


@router.patch("/brands/{brand_id}/policies/{policy_id}", response_model=BrandPolicyRead)
def update_policy(
    policy_id: UUID,
    payload: BrandPolicyUpdate,
    brand: Brand = Depends(require_brand_admin),
    actor: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> BrandPolicyRead:
    row = _get_child(entity=BrandPolicy, resource_id=policy_id, brand=brand, db=db)
    return _update_child(row=row, payload=payload, brand=brand, actor=actor, db=db, action="brand.policy_updated", resource_type="brand_policy", schema=BrandPolicyRead)


@router.delete("/brands/{brand_id}/policies/{policy_id}", status_code=204)
def delete_policy(
    policy_id: UUID,
    brand: Brand = Depends(require_brand_admin),
    actor: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    row = _get_child(entity=BrandPolicy, resource_id=policy_id, brand=brand, db=db)
    return _delete_child(row=row, brand=brand, actor=actor, db=db, action="brand.policy_deleted", resource_type="brand_policy")
