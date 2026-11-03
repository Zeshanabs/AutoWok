from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import (
    authorize_workspace,
    get_current_user,
    require_workspace_admin,
    require_workspace_member,
)
from app.core.config import get_settings
from app.db.session import get_db
from app.models import (
    AuditLog,
    Brand,
    MetaAuthorization,
    OAuthState,
    SocialAccount,
    SocialAccountCredential,
    User,
    WorkspaceMembership,
)
from app.schemas.social_accounts import (
    InstagramAccountOption,
    MetaPageOption,
    SocialAccountConnect,
    SocialAccountRead,
    SocialAccountUpdate,
    SocialPlatform,
)
from app.services.audit import record_audit
from app.services.meta_graph import META_SCOPES, MetaGraphClient, MetaGraphError
from app.services.rate_limit import enforce_rate_limit
from app.services.token_encryption import (
    TokenEncryptionNotConfigured,
    decrypt_token,
    encrypt_token,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["social accounts"])


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _meta_configuration_ready() -> bool:
    settings = get_settings()
    return bool(
        settings.meta_app_id.strip()
        and settings.meta_app_secret.strip()
        and settings.meta_redirect_uri.strip()
        and settings.meta_oauth_state_secret.strip()
    )


def _require_meta_configuration() -> None:
    if not _meta_configuration_ready():
        raise HTTPException(
            status_code=503,
            detail="Meta integration is not configured. Set its server-side application settings.",
        )


def _enforce_meta_rate_limit(
    request: Request,
    *,
    action: str,
    identity: str,
    limit: int = 30,
    window_seconds: int = 900,
) -> None:
    enforce_rate_limit(
        request,
        action=action,
        identity=identity,
        limit=limit,
        window_seconds=window_seconds,
        category="Meta integration",
    )


def _state_digest(value: str) -> str:
    secret = get_settings().meta_oauth_state_secret.encode("utf-8")
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _frontend_redirect(*, status_value: str, workspace_id: UUID | None = None) -> str:
    origin = get_settings().cors_origins_list[0].rstrip("/")
    query = f"meta={status_value}"
    if workspace_id:
        query += f"&workspace_id={workspace_id}"
    return f"{origin}/settings/social-accounts?{query}"


def _safe_graph_http_error(error: MetaGraphError) -> HTTPException:
    if error.status_code == 504:
        return HTTPException(status_code=504, detail="Meta did not respond before the timeout.")
    if error.code == 190:
        return HTTPException(
            status_code=409,
            detail="The Meta authorization has expired or was revoked. Reconnect the account.",
        )
    if error.code == 200 or error.status_code == 403:
        return HTTPException(
            status_code=403,
            detail="Meta denied access. Confirm the app permissions and Page access.",
        )
    if error.status_code == 429:
        return HTTPException(
            status_code=429,
            detail="Meta temporarily rate-limited this request. Try again later.",
        )
    return HTTPException(
        status_code=502,
        detail="Meta could not complete the request. Try again later.",
    )


def _authorization(
    db: DBSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
) -> MetaAuthorization:
    authorization = (
        db.query(MetaAuthorization)
        .filter(
            MetaAuthorization.workspace_id == workspace_id,
            MetaAuthorization.authorized_by == user_id,
        )
        .first()
    )
    if authorization is None:
        raise HTTPException(
            status_code=409,
            detail="Connect a Meta account before discovering Pages or Instagram accounts.",
        )
    if (
        authorization.access_token_expires_at is not None
        and _utc(authorization.access_token_expires_at) <= datetime.now(timezone.utc)
    ):
        raise HTTPException(
            status_code=409,
            detail="The Meta authorization expired. Reconnect the Meta account.",
        )
    return authorization


def _decrypt_authorization(authorization: MetaAuthorization) -> str:
    try:
        return decrypt_token(authorization.encrypted_user_access_token)
    except TokenEncryptionNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _require_brand_workspace(
    db: DBSession,
    brand_id: UUID | None,
    workspace_id: UUID,
) -> None:
    if brand_id is None:
        return
    brand = (
        db.query(Brand)
        .filter(Brand.id == brand_id, Brand.workspace_id == workspace_id)
        .first()
    )
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found in this workspace.")


def _page_picture(page: dict[str, Any]) -> str | None:
    picture = page.get("picture")
    data = picture.get("data") if isinstance(picture, dict) else None
    url = data.get("url") if isinstance(data, dict) else None
    return url if isinstance(url, str) else None


def _listed_pages(access_token: str) -> list[dict[str, Any]]:
    try:
        with MetaGraphClient() as graph:
            return graph.list_pages(access_token)
    except MetaGraphError as exc:
        raise _safe_graph_http_error(exc) from exc


def _load_pages(
    db: DBSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
) -> tuple[MetaAuthorization, list[dict[str, Any]]]:
    authorization = _authorization(db, workspace_id=workspace_id, user_id=user_id)
    return authorization, _listed_pages(_decrypt_authorization(authorization))


def _persist_account(
    db: DBSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    platform: SocialPlatform,
    platform_account_id: str,
    username: str | None,
    display_name: str,
    profile_image_url: str | None,
    account_type: str | None,
    parent_account_id: UUID | None,
    brand_id: UUID | None,
    scopes: list[str],
    access_token: str,
) -> SocialAccount:
    account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.workspace_id == workspace_id,
            SocialAccount.platform == platform.value,
            SocialAccount.platform_account_id == platform_account_id,
        )
        .first()
    )
    if account is None:
        account = SocialAccount(
            workspace_id=workspace_id,
            platform=platform.value,
            platform_account_id=platform_account_id,
            connected_by=user_id,
            display_name=display_name,
        )
        db.add(account)
    account.brand_id = brand_id
    account.username = username
    account.display_name = display_name
    account.profile_image_url = profile_image_url
    account.account_type = account_type
    account.parent_account_id = parent_account_id
    account.connection_status = "connected"
    account.granted_scopes = scopes
    account.connected_by = user_id
    account.connected_at = datetime.now(timezone.utc)
    account.last_error_code = None

    encrypted_token = encrypt_token(access_token)
    if account.credential is None:
        account.credential = SocialAccountCredential(
            encrypted_access_token=encrypted_token,
            token_type="bearer",
            encryption_version=1,
        )
    else:
        account.credential.encrypted_access_token = encrypted_token
        account.credential.encrypted_refresh_token = None
        account.credential.access_token_expires_at = None
        account.credential.refresh_token_expires_at = None
    db.flush()
    return account


@router.get("/oauth/meta/authorize")
def authorize_meta(
    workspace_id: UUID,
    request: Request,
    brand_id: UUID | None = None,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> RedirectResponse:
    _enforce_meta_rate_limit(
        request,
        action="meta-oauth-authorize",
        identity=f"{workspace_id}:{current_user.id}",
        limit=10,
        window_seconds=900,
    )
    _require_meta_configuration()
    _require_brand_workspace(db, brand_id, workspace_id)
    try:
        encrypt_token("configuration-check")
    except TokenEncryptionNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    state = secrets.token_urlsafe(32)
    db.add(
        OAuthState(
            state_hash=_state_digest(state),
            provider="meta",
            user_id=current_user.id,
            workspace_id=workspace_id,
            brand_id=brand_id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
    )
    db.commit()
    with MetaGraphClient() as graph:
        return RedirectResponse(
            graph.authorization_url(state=state),
            status_code=status.HTTP_302_FOUND,
        )


def _consume_oauth_state(
    db: DBSession,
    *,
    state: str,
    current_user: User,
) -> OAuthState | None:
    oauth_state = (
        db.query(OAuthState)
        .filter(OAuthState.state_hash == _state_digest(state), OAuthState.provider == "meta")
        .with_for_update()
        .first()
    )
    now = datetime.now(timezone.utc)
    if (
        oauth_state is None
        or oauth_state.user_id != current_user.id
        or oauth_state.consumed_at is not None
        or _utc(oauth_state.expires_at) <= now
    ):
        return None
    authorize_workspace(
        oauth_state.workspace_id,
        current_user,
        db,
        {"OWNER", "ADMIN"},
    )
    oauth_state.consumed_at = now
    db.commit()
    return oauth_state


@router.get("/oauth/meta/callback")
def meta_callback(
    state: str,
    request: Request,
    code: str | None = None,
    error: str | None = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> RedirectResponse:
    _enforce_meta_rate_limit(
        request,
        action="meta-oauth-callback",
        identity=str(current_user.id),
        limit=20,
        window_seconds=900,
    )
    _require_meta_configuration()
    oauth_state = _consume_oauth_state(db, state=state, current_user=current_user)
    if oauth_state is None:
        raise HTTPException(status_code=400, detail="The Meta authorization state is invalid or expired.")
    if error or not code:
        return RedirectResponse(
            _frontend_redirect(status_value="denied", workspace_id=oauth_state.workspace_id),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        with MetaGraphClient() as graph:
            access_token, expires_in = graph.exchange_code(code)
            user_data = graph.get_user(access_token)
            meta_user_id = user_data.get("id")
            if not isinstance(meta_user_id, str) or not meta_user_id:
                raise MetaGraphError(502)
            scopes = graph.get_permissions(access_token)
            if not set(META_SCOPES).issubset(scopes):
                return RedirectResponse(
                    _frontend_redirect(
                        status_value="permissions",
                        workspace_id=oauth_state.workspace_id,
                    ),
                    status_code=status.HTTP_303_SEE_OTHER,
                )
    except MetaGraphError:
        logger.warning("Meta OAuth callback failed for workspace %s", oauth_state.workspace_id)
        return RedirectResponse(
            _frontend_redirect(status_value="failed", workspace_id=oauth_state.workspace_id),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        encrypted_token = encrypt_token(access_token)
    except TokenEncryptionNotConfigured:
        logger.error("Meta token encryption is not configured")
        return RedirectResponse(
            _frontend_redirect(status_value="configuration", workspace_id=oauth_state.workspace_id),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    authorization = (
        db.query(MetaAuthorization)
        .filter(
            MetaAuthorization.workspace_id == oauth_state.workspace_id,
            MetaAuthorization.authorized_by == current_user.id,
        )
        .first()
    )
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        if expires_in is not None
        else None
    )
    if authorization is None:
        authorization = MetaAuthorization(
            workspace_id=oauth_state.workspace_id,
            authorized_by=current_user.id,
            meta_user_id=meta_user_id,
            encrypted_user_access_token=encrypted_token,
            granted_scopes=scopes,
            access_token_expires_at=expires_at,
        )
        db.add(authorization)
    else:
        authorization.meta_user_id = meta_user_id
        authorization.encrypted_user_access_token = encrypted_token
        authorization.granted_scopes = scopes
        authorization.access_token_expires_at = expires_at
    db.flush()
    record_audit(
        db,
        action="meta.authorization.connected",
        resource_type="meta_authorization",
        actor_user_id=current_user.id,
        workspace_id=oauth_state.workspace_id,
        resource_id=authorization.id if authorization.id else None,
        metadata={"permissions": scopes},
    )
    db.commit()
    return RedirectResponse(
        _frontend_redirect(status_value="connected", workspace_id=oauth_state.workspace_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/oauth/meta/refresh")
def refresh_meta_authorization(
    workspace_id: UUID,
    request: Request,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, str]:
    _enforce_meta_rate_limit(
        request,
        action="meta-refresh",
        identity=f"{workspace_id}:{current_user.id}",
        limit=10,
        window_seconds=900,
    )
    _require_meta_configuration()
    authorization = _authorization(db, workspace_id=workspace_id, user_id=current_user.id)
    current_token = _decrypt_authorization(authorization)
    try:
        with MetaGraphClient() as graph:
            refreshed_token, expires_in = graph.refresh_user_token(current_token)
            user_data = graph.get_user(refreshed_token)
            scopes = graph.get_permissions(refreshed_token)
            pages = graph.list_pages(refreshed_token)
    except MetaGraphError as exc:
        raise _safe_graph_http_error(exc) from exc

    page_by_id = {
        page.get("id"): page
        for page in pages
        if isinstance(page.get("id"), str) and isinstance(page.get("access_token"), str)
    }
    for account in (
        db.query(SocialAccount)
        .filter(
            SocialAccount.workspace_id == workspace_id,
            SocialAccount.connection_status != "disconnected",
        )
        .all()
    ):
        page = page_by_id.get(
            account.platform_account_id
            if account.platform == SocialPlatform.FACEBOOK_PAGE.value
            else next(
                (
                    page_id
                    for page_id, page_data in page_by_id.items()
                    if isinstance(page_data.get("instagram_business_account"), dict)
                    and page_data["instagram_business_account"].get("id")
                    == account.platform_account_id
                ),
                None,
            )
        )
        if page and account.credential:
            account.credential.encrypted_access_token = encrypt_token(page["access_token"])
            account.credential.access_token_expires_at = None
            account.credential.updated_at = datetime.now(timezone.utc)
            account.granted_scopes = scopes
            account.connection_status = "connected"
            account.last_error_code = None
    authorization.meta_user_id = str(user_data.get("id", authorization.meta_user_id))
    authorization.encrypted_user_access_token = encrypt_token(refreshed_token)
    authorization.access_token_expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        if expires_in is not None
        else None
    )
    authorization.granted_scopes = scopes
    record_audit(
        db,
        action="meta.authorization.refreshed",
        resource_type="meta_authorization",
        actor_user_id=current_user.id,
        workspace_id=workspace_id,
        resource_id=authorization.id,
        metadata={},
    )
    db.commit()
    return {"status": "refreshed", "message": "Meta authorization refreshed."}


@router.get("/workspaces/{workspace_id}/social-accounts/meta/facebook-pages", response_model=list[MetaPageOption])
def discover_facebook_pages(
    workspace_id: UUID,
    request: Request,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[MetaPageOption]:
    _enforce_meta_rate_limit(
        request,
        action="meta-page-discovery",
        identity=f"{workspace_id}:{current_user.id}",
    )
    authorization, pages = _load_pages(
        db, workspace_id=workspace_id, user_id=current_user.id
    )
    choices: list[MetaPageOption] = []
    for page in pages:
        tasks = page.get("tasks", [])
        if not isinstance(tasks, list) or not any(
            task in {"MANAGE", "CREATE_CONTENT"} for task in tasks
        ):
            continue
        if not isinstance(page.get("id"), str) or not isinstance(page.get("name"), str):
            continue
        choices.append(
            MetaPageOption(
                platform_account_id=page["id"],
                display_name=page["name"],
                username=page.get("username") if isinstance(page.get("username"), str) else None,
                category=page.get("category") if isinstance(page.get("category"), str) else None,
                profile_image_url=_page_picture(page),
                tasks=[task for task in tasks if isinstance(task, str)],
            )
        )
    return choices


@router.get(
    "/workspaces/{workspace_id}/social-accounts/meta/instagram-accounts",
    response_model=list[InstagramAccountOption],
)
def discover_instagram_accounts(
    workspace_id: UUID,
    request: Request,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[InstagramAccountOption]:
    _enforce_meta_rate_limit(
        request,
        action="meta-instagram-discovery",
        identity=f"{workspace_id}:{current_user.id}",
    )
    _, pages = _load_pages(db, workspace_id=workspace_id, user_id=current_user.id)
    choices: list[InstagramAccountOption] = []
    for page in pages:
        linked = page.get("instagram_business_account")
        if not isinstance(linked, dict):
            continue
        account_id = linked.get("id")
        account_type = linked.get("account_type")
        if (
            not isinstance(account_id, str)
            or account_type not in {"BUSINESS", "MEDIA_CREATOR"}
            or not isinstance(page.get("id"), str)
            or not isinstance(page.get("name"), str)
        ):
            continue
        choices.append(
            InstagramAccountOption(
                platform_account_id=account_id,
                username=linked.get("username")
                if isinstance(linked.get("username"), str)
                else None,
                account_type=account_type,
                profile_image_url=linked.get("profile_picture_url")
                if isinstance(linked.get("profile_picture_url"), str)
                else None,
                parent_page_id=page["id"],
                parent_page_name=page["name"],
            )
        )
    return choices


@router.post(
    "/workspaces/{workspace_id}/social-accounts/meta/connect",
    response_model=SocialAccountRead,
    status_code=status.HTTP_201_CREATED,
)
def connect_meta_account(
    workspace_id: UUID,
    payload: SocialAccountConnect,
    request: Request,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> SocialAccountRead:
    _enforce_meta_rate_limit(
        request,
        action="meta-account-connect",
        identity=f"{workspace_id}:{current_user.id}",
    )
    platform = SocialPlatform(payload.platform)
    _require_brand_workspace(db, payload.brand_id, workspace_id)
    authorization, pages = _load_pages(
        db, workspace_id=workspace_id, user_id=current_user.id
    )
    selected_page: dict[str, Any] | None = None
    if platform == SocialPlatform.FACEBOOK_PAGE:
        selected_page = next(
            (
                page
                for page in pages
                if page.get("id") == payload.platform_account_id
                and isinstance(page.get("access_token"), str)
                and isinstance(page.get("tasks"), list)
                and any(task in {"MANAGE", "CREATE_CONTENT"} for task in page["tasks"])
            ),
            None,
        )
        if selected_page is None:
            raise HTTPException(status_code=404, detail="Eligible Facebook Page not found.")
        page_token = selected_page["access_token"]
        instagram = selected_page.get("instagram_business_account")
        account_type = "PAGE"
        username = selected_page.get("username")
        name = selected_page.get("name")
        image = _page_picture(selected_page)
        parent_id = None
    else:
        selected_page = next(
            (
                page
                for page in pages
                if page.get("id") == payload.parent_page_id
                and isinstance(page.get("access_token"), str)
                and isinstance(page.get("tasks"), list)
                and any(task in {"MANAGE", "CREATE_CONTENT"} for task in page["tasks"])
            ),
            None,
        )
        instagram = (
            selected_page.get("instagram_business_account")
            if selected_page is not None
            else None
        )
        if (
            not isinstance(instagram, dict)
            or instagram.get("id") != payload.platform_account_id
            or instagram.get("account_type") not in {"BUSINESS", "MEDIA_CREATOR"}
        ):
            raise HTTPException(
                status_code=404,
                detail="Eligible Instagram Professional account not found on the selected Page.",
            )
        page_token = selected_page["access_token"]
        account_type = instagram["account_type"]
        username = instagram.get("username")
        name = instagram.get("username") or selected_page.get("name")
        image = instagram.get("profile_picture_url")
        parent = (
            db.query(SocialAccount)
            .filter(
                SocialAccount.workspace_id == workspace_id,
                SocialAccount.platform == SocialPlatform.FACEBOOK_PAGE.value,
                SocialAccount.platform_account_id == selected_page["id"],
                SocialAccount.connection_status != "disconnected",
            )
            .first()
        )
        parent_id = parent.id if parent else None

    if not isinstance(name, str) or not name:
        raise HTTPException(status_code=502, detail="Meta did not return account metadata.")
    try:
        account = _persist_account(
            db,
            workspace_id=workspace_id,
            user_id=current_user.id,
            platform=platform,
            platform_account_id=payload.platform_account_id,
            username=username if isinstance(username, str) else None,
            display_name=name,
            profile_image_url=image if isinstance(image, str) else None,
            account_type=account_type,
            parent_account_id=parent_id,
            brand_id=payload.brand_id,
            scopes=authorization.granted_scopes,
            access_token=page_token,
        )
        record_audit(
            db,
            action="social_account.connected",
            resource_type="social_account",
            actor_user_id=current_user.id,
            workspace_id=workspace_id,
            resource_id=account.id,
            metadata={"platform": platform.value},
        )
        db.commit()
        db.refresh(account)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This account is already connected.") from exc
    return SocialAccountRead.model_validate(account)


@router.get("/workspaces/{workspace_id}/social-accounts", response_model=list[SocialAccountRead])
def list_social_accounts(
    workspace_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> list[SocialAccountRead]:
    accounts = (
        db.query(SocialAccount)
        .filter(SocialAccount.workspace_id == workspace_id)
        .order_by(SocialAccount.created_at.desc())
        .all()
    )
    return [SocialAccountRead.model_validate(account) for account in accounts]


def _get_social_account(
    db: DBSession, workspace_id: UUID, account_id: UUID
) -> SocialAccount:
    account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.id == account_id,
            SocialAccount.workspace_id == workspace_id,
        )
        .first()
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Social account not found.")
    return account


@router.get(
    "/workspaces/{workspace_id}/social-accounts/{account_id}",
    response_model=SocialAccountRead,
)
def get_social_account(
    workspace_id: UUID,
    account_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_member),
    db: DBSession = Depends(get_db),
) -> SocialAccountRead:
    return SocialAccountRead.model_validate(_get_social_account(db, workspace_id, account_id))


@router.patch(
    "/workspaces/{workspace_id}/social-accounts/{account_id}",
    response_model=SocialAccountRead,
)
def update_social_account(
    workspace_id: UUID,
    account_id: UUID,
    payload: SocialAccountUpdate,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> SocialAccountRead:
    account = _get_social_account(db, workspace_id, account_id)
    changes = payload.model_dump(exclude_unset=True)
    _require_brand_workspace(db, changes.get("brand_id"), workspace_id)
    account.brand_id = changes.get("brand_id")
    record_audit(
        db,
        action="social_account.updated",
        resource_type="social_account",
        actor_user_id=current_user.id,
        workspace_id=workspace_id,
        resource_id=account.id,
        metadata={"fields": list(changes)},
    )
    db.commit()
    db.refresh(account)
    return SocialAccountRead.model_validate(account)


@router.post(
    "/workspaces/{workspace_id}/social-accounts/{account_id}/verify",
    response_model=SocialAccountRead,
)
def verify_social_account(
    workspace_id: UUID,
    account_id: UUID,
    request: Request,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> SocialAccountRead:
    _enforce_meta_rate_limit(
        request,
        action="meta-account-verify",
        identity=f"{workspace_id}:{current_user.id}",
    )
    account = _get_social_account(db, workspace_id, account_id)
    if account.connection_status == "disconnected" or account.credential is None:
        raise HTTPException(status_code=409, detail="Reconnect this account before verifying it.")
    try:
        token = decrypt_token(account.credential.encrypted_access_token)
    except TokenEncryptionNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        with MetaGraphClient() as graph:
            metadata = graph.get_social_account(
                account_id=account.platform_account_id,
                platform=account.platform,
                access_token=token,
            )
    except MetaGraphError as exc:
        account.connection_status = "expired" if exc.code == 190 else "revoked" if exc.code == 200 else "error"
        account.last_error_code = (
            "META_TOKEN_INVALID"
            if exc.code == 190
            else "META_PERMISSION_REVOKED"
            if exc.code == 200
            else "META_UNAVAILABLE"
        )
        db.commit()
        raise _safe_graph_http_error(exc) from exc
    account.display_name = metadata.get("name") or metadata.get("username") or account.display_name
    account.username = metadata.get("username") or account.username
    if isinstance(metadata.get("profile_picture_url"), str):
        account.profile_image_url = metadata["profile_picture_url"]
    account.last_verified_at = datetime.now(timezone.utc)
    account.connection_status = "connected"
    account.last_error_code = None
    record_audit(
        db,
        action="social_account.verified",
        resource_type="social_account",
        actor_user_id=current_user.id,
        workspace_id=workspace_id,
        resource_id=account.id,
        metadata={"platform": account.platform},
    )
    db.commit()
    db.refresh(account)
    return SocialAccountRead.model_validate(account)


@router.post(
    "/workspaces/{workspace_id}/social-accounts/{account_id}/disconnect",
    response_model=SocialAccountRead,
)
def disconnect_social_account(
    workspace_id: UUID,
    account_id: UUID,
    membership: WorkspaceMembership = Depends(require_workspace_admin),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> SocialAccountRead:
    account = _get_social_account(db, workspace_id, account_id)
    if account.credential is not None:
        db.delete(account.credential)
    account.connection_status = "disconnected"
    account.last_error_code = None
    record_audit(
        db,
        action="social_account.disconnected",
        resource_type="social_account",
        actor_user_id=current_user.id,
        workspace_id=workspace_id,
        resource_id=account.id,
        metadata={"platform": account.platform},
    )
    db.commit()
    db.refresh(account)
    return SocialAccountRead.model_validate(account)
