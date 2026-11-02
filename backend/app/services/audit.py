from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from app.models import AuditLog


def record_audit(
    db: DBSession,
    *,
    action: str,
    resource_type: str,
    actor_user_id: UUID | None = None,
    workspace_id: UUID | None = None,
    resource_id: UUID | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            details=metadata or {},
        )
    )
