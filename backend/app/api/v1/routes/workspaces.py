from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import (
    get_current_user,
    require_workspace_admin,
    require_workspace_member,
)
from app.db.session import get_db
from app.models import User, Workspace, WorkspaceMembership
from app.schemas.workspaces import (
    WorkspaceCreate,
    WorkspaceDetail,
    WorkspaceMemberAdd,
    WorkspaceMemberRead,
    WorkspaceRole,
    WorkspaceRoleUpdate,
    WorkspaceUpdate,
)
from app.services.audit import record_audit
from app.services.identity import generate_workspace_slug, normalize_email

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _workspace_detail(workspace: Workspace) -> WorkspaceDetail:
    return WorkspaceDetail(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        owner_id=workspace.owner_id,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


def _member_read(membership: WorkspaceMembership) -> WorkspaceMemberRead:
    return WorkspaceMemberRead(
        user_id=membership.user.id,
        full_name=membership.user.full_name,
        email=membership.user.email,
        role=WorkspaceRole(membership.role),
        joined_at=membership.joined_at,
    )


@router.post("", response_model=WorkspaceDetail, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> WorkspaceDetail:
    workspace = Workspace(
        name=payload.name,
        slug=generate_workspace_slug(payload.name),
        owner_id=current_user.id,
    )
    try:
        db.add(workspace)
        db.flush()
        db.add(
            WorkspaceMembership(
                workspace_id=workspace.id,
                user_id=current_user.id,
                role=WorkspaceRole.OWNER.value,
            )
        )
        record_audit(
            db,
            action="workspace.created",
            resource_type="workspace",
            actor_user_id=current_user.id,
            workspace_id=workspace.id,
            resource_id=workspace.id,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Workspace could not be created.") from exc
    return _workspace_detail(workspace)


@router.get("", response_model=list[WorkspaceDetail])
def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[WorkspaceDetail]:
    memberships = (
        db.query(WorkspaceMembership)
        .filter(WorkspaceMembership.user_id == current_user.id)
        .all()
    )
    return [_workspace_detail(membership.workspace) for membership in memberships]


@router.get("/{workspace_id}", response_model=WorkspaceDetail)
def get_workspace(
    workspace_access: WorkspaceMembership = Depends(require_workspace_member),
) -> WorkspaceDetail:
    return _workspace_detail(workspace_access.workspace)


@router.patch("/{workspace_id}", response_model=WorkspaceDetail)
def update_workspace(
    payload: WorkspaceUpdate,
    workspace_access: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> WorkspaceDetail:
    workspace = workspace_access.workspace
    workspace.name = payload.name
    record_audit(
        db,
        action="workspace.updated",
        resource_type="workspace",
        actor_user_id=current_user.id,
        workspace_id=workspace.id,
        resource_id=workspace.id,
        metadata={"fields": ["name"]},
    )
    db.commit()
    return _workspace_detail(workspace)


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberRead])
def list_members(
    workspace_access: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> list[WorkspaceMemberRead]:
    memberships = (
        db.query(WorkspaceMembership)
        .filter(WorkspaceMembership.workspace_id == workspace_access.workspace_id)
        .order_by(WorkspaceMembership.joined_at)
        .all()
    )
    return [_member_read(membership) for membership in memberships]


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberRead,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    payload: WorkspaceMemberAdd,
    workspace_access: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> WorkspaceMemberRead:
    if payload.role == WorkspaceRole.OWNER:
        raise HTTPException(status_code=400, detail="Ownership transfer is not supported.")
    email = normalize_email(str(payload.email))
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Registered user not found.")
    if (
        db.query(WorkspaceMembership.id)
        .filter(
            WorkspaceMembership.workspace_id == workspace_access.workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
        .first()
        is not None
    ):
        raise HTTPException(status_code=409, detail="User is already a workspace member.")

    membership = WorkspaceMembership(
        workspace_id=workspace_access.workspace_id,
        user_id=user.id,
        role=payload.role.value,
    )
    db.add(membership)
    record_audit(
        db,
        action="workspace.member_added",
        resource_type="membership",
        actor_user_id=current_user.id,
        workspace_id=workspace_access.workspace_id,
        resource_id=user.id,
        metadata={"role": payload.role.value},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="User is already a workspace member.") from exc
    db.refresh(membership)
    return _member_read(membership)


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_member(
    workspace_id: UUID,
    user_id: UUID,
    workspace_access: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    target = (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.workspace_id == workspace_access.workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
        .first()
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Workspace member not found.")
    if target.role == WorkspaceRole.OWNER or user_id == workspace_access.workspace.owner_id:
        raise HTTPException(status_code=400, detail="The workspace owner cannot be removed.")

    record_audit(
        db,
        action="workspace.member_removed",
        resource_type="membership",
        actor_user_id=current_user.id,
        workspace_id=workspace_access.workspace_id,
        resource_id=user_id,
    )
    db.delete(target)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/{workspace_id}/members/{user_id}/role",
    response_model=WorkspaceMemberRead,
)
def update_member_role(
    workspace_id: UUID,
    user_id: UUID,
    payload: WorkspaceRoleUpdate,
    workspace_access: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> WorkspaceMemberRead:
    target = (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.workspace_id == workspace_access.workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
        .first()
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Workspace member not found.")
    if target.role == WorkspaceRole.OWNER or user_id == workspace_access.workspace.owner_id:
        raise HTTPException(status_code=400, detail="The workspace owner role cannot be changed.")
    if payload.role == WorkspaceRole.OWNER:
        raise HTTPException(status_code=400, detail="Ownership transfer is not supported.")
    target.role = payload.role.value
    record_audit(
        db,
        action="workspace.member_role_changed",
        resource_type="membership",
        actor_user_id=current_user.id,
        workspace_id=workspace_access.workspace_id,
        resource_id=user_id,
        metadata={"role": payload.role.value},
    )
    db.commit()
    return _member_read(target)
