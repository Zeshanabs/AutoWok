from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import (
    get_current_user,
    require_workspace_admin,
    require_workspace_member,
)
from app.db.session import get_db
from app.models import AIProviderConfig, User, WorkspaceMembership
from app.services.audit import record_audit
from app.services.groq import GroqError, GroqService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/ai-providers/groq",
    tags=["Groq provider"],
)


class GroqTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    model_name: str | None = Field(default=None, min_length=1, max_length=160)


@router.get("/status")
def groq_status(
    workspace_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> dict:
    return GroqService(db, workspace_id).configuration_status()


@router.get("/models")
def groq_models(
    workspace_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    db: DBSession = Depends(get_db),
) -> dict[str, list[str]]:
    try:
        return {"models": GroqService(db, workspace_id).list_models()}
    except GroqError as exc:
        headers = {"Retry-After": exc.retry_after} if getattr(exc, "retry_after", None) else None
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
            headers=headers,
        ) from exc


@router.post("/test")
def test_groq_connection(
    workspace_id: UUID,
    payload: GroqTestRequest | None = None,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict:
    provider = (
        db.query(AIProviderConfig)
        .filter(
            AIProviderConfig.workspace_id == workspace_id,
            AIProviderConfig.provider_name == "groq",
        )
        .first()
    )
    tested_at = datetime.now(timezone.utc)
    try:
        result = GroqService(db, workspace_id).test_connection(
            payload.model_name if payload else None
        )
        test_status = "success"
    except GroqError as exc:
        test_status = (
            "rate_limited"
            if exc.status_code == 429
            else "invalid_credentials"
            if exc.status_code == 401
            else "failed"
        )
        if provider:
            provider.last_tested_at = tested_at
            provider.last_test_status = test_status
            db.commit()
        headers = {"Retry-After": exc.retry_after} if getattr(exc, "retry_after", None) else None
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
            headers=headers,
        ) from exc

    if provider:
        provider.last_tested_at = tested_at
        provider.last_test_status = test_status
    record_audit(
        db,
        action="ai_provider.groq_tested",
        resource_type="ai_provider_config",
        actor_user_id=current_user.id,
        workspace_id=workspace_id,
        resource_id=provider.id if provider else None,
        metadata={"status": test_status},
    )
    db.commit()
    return {
        "status": test_status,
        "model": result["model"],
        "source": GroqService(db, workspace_id).configuration_status()["source"],
        "tested_at": tested_at,
    }
