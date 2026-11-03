from __future__ import annotations

from typing import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import authorize_workspace, get_current_user
from app.db.session import get_db
from app.models import Brand, User


def get_brand(
    brand_id: UUID,
    current_user: User,
    db: DBSession,
    allowed_roles: set[str] | None = None,
) -> Brand:
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if brand is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brand not found.")
    authorize_workspace(brand.workspace_id, current_user, db, allowed_roles)
    return brand


def require_brand_role(*roles: str) -> Callable[..., Brand]:
    allowed_roles = set(roles)
    require_active = allowed_roles == {"OWNER", "ADMIN"}

    def dependency(
        brand_id: UUID,
        current_user: User = Depends(get_current_user),
        db: DBSession = Depends(get_db),
    ) -> Brand:
        brand = get_brand(brand_id, current_user, db, allowed_roles)
        if require_active and brand.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Archived brands cannot be changed.",
            )
        return brand

    return dependency


require_brand_member = require_brand_role("OWNER", "ADMIN", "MEMBER")
require_brand_admin = require_brand_role("OWNER", "ADMIN")
