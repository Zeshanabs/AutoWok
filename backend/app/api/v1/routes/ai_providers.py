from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit
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
from app.models import AIProviderConfig, User, WorkspaceMembership
from app.schemas.brands import (
    AIProviderCreate,
    AIProviderRead,
    AIProviderTestResponse,
    AIProviderUpdate,
    ProviderName,
)
from app.services.ai_encryption import EncryptionNotConfigured, decrypt_api_key, encrypt_api_key
from app.services.ai_providers import (
    PROVIDER_REGISTRY,
    ProviderTestResult,
    ProviderTestStatus,
    PinnedHTTPTransport,
    validate_provider_endpoint,
    validate_public_custom_endpoint,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/workspaces/{workspace_id}/ai-providers", tags=["AI providers"])


def _read_provider(provider: AIProviderConfig) -> AIProviderRead:
    return AIProviderRead(
        id=provider.id,
        workspace_id=provider.workspace_id,
        provider_name=ProviderName(provider.provider_name),
        display_name=provider.display_name,
        model_name=provider.model_name,
        base_url=provider.base_url,
        api_key_configured=bool(provider.encrypted_api_key),
        masked_api_key="********" if provider.encrypted_api_key else "",
        is_active=provider.is_active,
        is_default=provider.is_default,
        configuration=provider.configuration,
        created_by=provider.created_by,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
        last_tested_at=provider.last_tested_at,
        last_test_status=provider.last_test_status,
    )


def _get_provider(
    workspace_id: UUID,
    provider_id: UUID,
    db: DBSession,
) -> AIProviderConfig:
    provider = (
        db.query(AIProviderConfig)
        .filter(
            AIProviderConfig.id == provider_id,
            AIProviderConfig.workspace_id == workspace_id,
        )
        .first()
    )
    if provider is None:
        raise HTTPException(status_code=404, detail="AI provider configuration not found.")
    return provider


def _validate_endpoint(provider_name: ProviderName, base_url: str | None) -> str | None:
    try:
        return validate_provider_endpoint(provider_name, base_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _validate_encryption_key() -> None:
    try:
        encrypt_api_key("configuration-check")
    except EncryptionNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _unset_workspace_default(
    db: DBSession,
    workspace_id: UUID,
    except_id: UUID | None = None,
) -> None:
    query = db.query(AIProviderConfig).filter(
        AIProviderConfig.workspace_id == workspace_id,
        AIProviderConfig.is_default.is_(True),
    )
    if except_id is not None:
        query = query.filter(AIProviderConfig.id != except_id)
    query.update(
        {AIProviderConfig.is_default: False},
        synchronize_session="fetch",
    )


def _audit_provider_change(
    db: DBSession,
    *,
    action: str,
    provider: AIProviderConfig,
    actor: User,
    fields: list[str] | None = None,
) -> None:
    record_audit(
        db,
        action=action,
        resource_type="ai_provider_config",
        actor_user_id=actor.id,
        workspace_id=provider.workspace_id,
        resource_id=provider.id,
        metadata={"fields": fields} if fields else {},
    )


def _test_connection(
    provider_name: ProviderName,
    api_key: str,
    base_url: str | None,
) -> ProviderTestResult:
    if provider_name == ProviderName.OPENAI_COMPATIBLE:
        if base_url is None:
            raise HTTPException(status_code=422, detail="A custom provider endpoint is required.")
        try:
            addresses = validate_public_custom_endpoint(base_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        host = urlsplit(base_url).hostname
        if host is None:
            raise HTTPException(status_code=422, detail="The custom provider host is invalid.")
        transport = PinnedHTTPTransport(host, addresses)
        return PROVIDER_REGISTRY[provider_name].test_connection(
            api_key=api_key,
            base_url=base_url,
            transport=transport,
        )
    return PROVIDER_REGISTRY[provider_name].test_connection(
        api_key=api_key,
        base_url=base_url,
    )


@router.get("", response_model=list[AIProviderRead])
def list_ai_providers(
    workspace_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> list[AIProviderRead]:
    providers = (
        db.query(AIProviderConfig)
        .filter(AIProviderConfig.workspace_id == workspace_id)
        .order_by(AIProviderConfig.created_at.desc())
        .all()
    )
    return [_read_provider(provider) for provider in providers]


@router.post("", response_model=AIProviderRead, status_code=status.HTTP_201_CREATED)
def create_ai_provider(
    workspace_id: UUID,
    payload: AIProviderCreate,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> AIProviderRead:
    _validate_encryption_key()
    base_url = _validate_endpoint(payload.provider_name, str(payload.base_url) if payload.base_url else None)
    try:
        encrypted_key = encrypt_api_key(payload.api_key.get_secret_value())
    except EncryptionNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if payload.is_default:
        _unset_workspace_default(db, workspace_id)
    provider = AIProviderConfig(
        workspace_id=workspace_id,
        provider_name=str(payload.provider_name),
        display_name=payload.display_name,
        model_name=payload.model_name,
        base_url=base_url,
        encrypted_api_key=encrypted_key,
        is_active=payload.is_active,
        is_default=payload.is_default,
        configuration=payload.configuration,
        created_by=current_user.id,
    )
    db.add(provider)
    try:
        db.flush()
        _audit_provider_change(
            db, action="ai_provider.created", provider=provider, actor=current_user
        )
        db.commit()
        db.refresh(provider)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The workspace already has a default AI provider.",
        ) from exc
    return _read_provider(provider)


@router.get("/{provider_id}", response_model=AIProviderRead)
def get_ai_provider(
    workspace_id: UUID,
    provider_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> AIProviderRead:
    return _read_provider(_get_provider(workspace_id, provider_id, db))


@router.patch("/{provider_id}", response_model=AIProviderRead)
def update_ai_provider(
    workspace_id: UUID,
    provider_id: UUID,
    payload: AIProviderUpdate,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> AIProviderRead:
    provider = _get_provider(workspace_id, provider_id, db)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field is required.")
    if changes.get("is_active") is False and "is_default" not in changes:
        changes["is_default"] = False
    next_is_default = changes.get("is_default", provider.is_default)
    next_is_active = changes.get("is_active", provider.is_active)
    if next_is_default and not next_is_active:
        raise HTTPException(status_code=422, detail="An inactive provider cannot be the default.")
    if "base_url" in changes:
        changes["base_url"] = str(changes["base_url"]) if changes["base_url"] else None
        changes["last_tested_at"] = None
        changes["last_test_status"] = None
    base_url = changes.get("base_url", provider.base_url)
    _validate_endpoint(ProviderName(provider.provider_name), base_url)
    if "api_key" in changes:
        _validate_encryption_key()
        secret = changes.pop("api_key")
        if secret is None:
            raise HTTPException(status_code=422, detail="A replacement API key cannot be null.")
        try:
            changes["encrypted_api_key"] = encrypt_api_key(secret.get_secret_value())
        except EncryptionNotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        changes["last_tested_at"] = None
        changes["last_test_status"] = None
        changed_secret = True
    else:
        changed_secret = False
    for field, value in changes.items():
        column = provider.__table__.columns.get(field)
        if column is None:
            raise HTTPException(status_code=422, detail="Unsupported provider field.")
        if value is None and not column.nullable:
            raise HTTPException(
                status_code=422,
                detail=f"{field} cannot be null.",
            )
    if changes.get("is_default") is True:
        _unset_workspace_default(db, workspace_id, except_id=provider.id)
    elif changes.get("is_default") is False or changes.get("is_active") is False:
        changes["is_default"] = False

    fields = [field for field in changes if field != "encrypted_api_key"]
    if changed_secret:
        fields.append("api_key")
    for field, value in changes.items():
        setattr(provider, field, value)
    _audit_provider_change(
        db,
        action="ai_provider.updated",
        provider=provider,
        actor=current_user,
        fields=fields,
    )
    try:
        db.commit()
        db.refresh(provider)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The workspace already has a default AI provider.",
        ) from exc
    return _read_provider(provider)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_provider(
    workspace_id: UUID,
    provider_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    provider = _get_provider(workspace_id, provider_id, db)
    _audit_provider_change(
        db, action="ai_provider.deleted", provider=provider, actor=current_user
    )
    db.delete(provider)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{provider_id}/test", response_model=AIProviderTestResponse)
def test_ai_provider(
    workspace_id: UUID,
    provider_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> AIProviderTestResponse:
    provider = _get_provider(workspace_id, provider_id, db)
    try:
        api_key = decrypt_api_key(provider.encrypted_api_key)
    except EncryptionNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    result = _test_connection(
        ProviderName(provider.provider_name),
        api_key,
        provider.base_url,
    )
    tested_at = datetime.now(timezone.utc)
    provider.last_tested_at = tested_at
    provider.last_test_status = result.status.value
    _audit_provider_change(
        db,
        action="ai_provider.connection_tested",
        provider=provider,
        actor=current_user,
        fields=["last_test_status"],
    )
    db.commit()
    return AIProviderTestResponse(
        status=result.status.value,
        message=result.message,
        tested_at=tested_at,
    )
