from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import authorize_workspace, get_current_user
from app.api.v1.routes.content import _ensure_project_editable, _mark_project_revised
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Brand, ContentDraft, MediaAsset, SocialAccount, User
from app.schemas.media_assets import (
    DraftMediaAttachment,
    DraftPreview,
    MediaAccessUrl,
    MediaAssetRead,
    MediaAssetUpdate,
    PreviewMediaItem,
)
from app.services.audit import record_audit
from app.services.content_studio import ContentStudioService
from app.services.media_processing import MediaValidationError, max_upload_bytes, process_upload, sanitize_filename
from app.services.media_urls import sign_media_path, verify_signature
from app.services.publishing.eligibility import evaluate_eligibility
from app.services.storage import StorageError, storage_service

router = APIRouter(tags=["media assets"])
_CHUNK = 1024 * 1024


def _media_asset_read(asset: MediaAsset, *, duplicate: bool = False) -> MediaAssetRead:
    prefix = get_settings().api_v1_prefix
    return MediaAssetRead(
        id=asset.id,
        workspace_id=asset.workspace_id,
        brand_id=asset.brand_id,
        original_filename=asset.original_filename,
        title=asset.title,
        media_type=asset.mime_type.split("/")[0],
        mime_type=asset.mime_type,
        file_extension=asset.file_extension,
        file_size=asset.file_size,
        width=asset.width,
        height=asset.height,
        duration_seconds=asset.duration_seconds,
        checksum=asset.checksum,
        has_thumbnail=bool(asset.thumbnail_key),
        metadata_stripped=asset.metadata_stripped,
        storage_provider=asset.storage_provider,
        processing_status=asset.processing_status,
        uploaded_by=asset.uploaded_by,
        archived=asset.archived,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        content_url=f"{prefix}/media-assets/{asset.id}/content",
        download_url=f"{prefix}/media-assets/{asset.id}/download",
        thumbnail_url=f"{prefix}/media-assets/{asset.id}/thumbnail" if asset.thumbnail_key else None,
        duplicate=duplicate,
    )


def _get_asset(db: DBSession, user: User, media_id: UUID, *, allow_archived: bool = False) -> MediaAsset:
    asset = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if asset is None or (asset.archived and not allow_archived):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media asset not found.")
    authorize_workspace(asset.workspace_id, user, db)
    return asset


def _stream_file(asset: MediaAsset, key: str, media_type: str, *, download_name: str | None = None) -> Response:
    try:
        data = storage_service.read_file(key)
    except StorageError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored media file not found.") from exc
    headers = {"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"}
    if download_name:
        safe = sanitize_filename(download_name).replace('"', "")
        headers["Content-Disposition"] = f'attachment; filename="{safe}"'
    else:
        headers["Content-Disposition"] = "inline"
    return Response(content=data, media_type=media_type, headers=headers)


@router.get("/media-assets", response_model=list[MediaAssetRead])
def list_media_assets(
    workspace_id: UUID,
    media_type: str | None = Query(default=None, pattern="^(image|video)$"),
    brand_id: UUID | None = None,
    search: str | None = Query(default=None, max_length=200),
    include_archived: bool = False,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[MediaAssetRead]:
    authorize_workspace(workspace_id, current_user, db)
    query = db.query(MediaAsset).filter(MediaAsset.workspace_id == workspace_id)
    if not include_archived:
        query = query.filter(MediaAsset.archived.is_(False))
    if media_type:
        query = query.filter(MediaAsset.mime_type.like(f"{media_type}/%"))
    if brand_id:
        query = query.filter(MediaAsset.brand_id == brand_id)
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        from sqlalchemy import func

        query = query.filter(
            or_(func.lower(MediaAsset.original_filename).like(term), func.lower(MediaAsset.title).like(term))
        )
    assets = query.order_by(MediaAsset.created_at.desc()).limit(500).all()
    return [_media_asset_read(asset) for asset in assets]


@router.get("/media-assets/{media_id}", response_model=MediaAssetRead)
def get_media_asset(
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> MediaAssetRead:
    return _media_asset_read(_get_asset(db, current_user, media_id, allow_archived=True))


@router.post("/media-assets/upload", response_model=MediaAssetRead, status_code=status.HTTP_201_CREATED)
async def upload_media_asset(
    workspace_id: UUID = Form(...),
    brand_id: UUID | None = Form(default=None),
    title: str | None = Form(default=None, max_length=200),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> MediaAssetRead:
    authorize_workspace(workspace_id, current_user, db)
    if brand_id is not None:
        brand = db.query(Brand).filter(Brand.id == brand_id, Brand.workspace_id == workspace_id).first()
        if brand is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brand not found in this workspace.")

    limit = max_upload_bytes()
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Files must be {limit // (1024 * 1024)} MB or smaller.",
            )
        chunks.append(chunk)
    raw = b"".join(chunks)
    display_name = sanitize_filename(file.filename)

    try:
        processed = process_upload(raw, display_name)
    except MediaValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    checksum = hashlib.sha256(raw).hexdigest()
    existing_asset = (
        db.query(MediaAsset)
        .filter(
            MediaAsset.workspace_id == workspace_id,
            MediaAsset.checksum == checksum,
            MediaAsset.archived.is_(False),
        )
        .first()
    )
    if existing_asset is not None:
        return _media_asset_read(existing_asset, duplicate=True)

    asset_id = uuid4()
    storage_key = f"workspaces/{workspace_id}/media/{asset_id}.{processed.extension}"
    thumbnail_key = f"workspaces/{workspace_id}/thumbnails/{asset_id}.jpg" if processed.thumbnail else None
    try:
        storage_service.save_file(storage_key, processed.data)
        if thumbnail_key and processed.thumbnail:
            storage_service.save_file(thumbnail_key, processed.thumbnail)
    except StorageError as exc:
        for key in (storage_key, thumbnail_key):
            if key:
                try:
                    storage_service.delete_file(key)
                except StorageError:
                    pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The file could not be stored. Try again later.",
        ) from exc

    asset = MediaAsset(
        id=asset_id,
        workspace_id=workspace_id,
        brand_id=brand_id,
        original_filename=display_name,
        title=(" ".join(title.split()) or None) if title else None,
        storage_key=storage_key,
        mime_type=processed.mime_type,
        file_extension=processed.extension,
        file_size=len(processed.data),
        width=processed.width,
        height=processed.height,
        duration_seconds=processed.duration_seconds,
        checksum=checksum,
        thumbnail_key=thumbnail_key,
        storage_provider=storage_service.provider_name,
        processing_status="ready",
        metadata_stripped=processed.metadata_stripped,
        uploaded_by=current_user.id,
    )
    db.add(asset)
    record_audit(
        db,
        action="media.uploaded",
        resource_type="media_asset",
        actor_user_id=current_user.id,
        workspace_id=workspace_id,
        resource_id=asset_id,
        metadata={"mime_type": processed.mime_type, "size": len(processed.data)},
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        for key in (storage_key, thumbnail_key):
            if key:
                try:
                    storage_service.delete_file(key)
                except StorageError:
                    pass
        raise
    db.refresh(asset)
    return _media_asset_read(asset)


@router.patch("/media-assets/{media_id}", response_model=MediaAssetRead)
def update_media_asset(
    media_id: UUID,
    payload: MediaAssetUpdate,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> MediaAssetRead:
    asset = _get_asset(db, current_user, media_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field is required.")
    if "brand_id" in changes and changes["brand_id"] is not None:
        brand = db.query(Brand).filter(Brand.id == changes["brand_id"], Brand.workspace_id == asset.workspace_id).first()
        if brand is None:
            raise HTTPException(status_code=404, detail="Brand not found in this workspace.")
    for field, value in changes.items():
        setattr(asset, field, value)
    db.commit()
    db.refresh(asset)
    return _media_asset_read(asset)


@router.get("/media-assets/{media_id}/content")
def get_media_content(
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    asset = _get_asset(db, current_user, media_id)
    return _stream_file(asset, asset.storage_key, asset.mime_type)


@router.get("/media-assets/{media_id}/download")
def download_media_asset(
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    asset = _get_asset(db, current_user, media_id)
    return _stream_file(asset, asset.storage_key, asset.mime_type, download_name=asset.original_filename)


@router.get("/media-assets/{media_id}/thumbnail")
def get_media_asset_thumbnail(
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    asset = _get_asset(db, current_user, media_id)
    if not asset.thumbnail_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail not generated.")
    return _stream_file(asset, asset.thumbnail_key, "image/jpeg")


@router.post("/media-assets/{media_id}/access-url", response_model=MediaAccessUrl)
def create_media_access_url(
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> MediaAccessUrl:
    from app.services.media_urls import SignedUrlNotConfigured

    asset = _get_asset(db, current_user, media_id)
    ttl = min(get_settings().media_signed_url_ttl_seconds, 900)
    try:
        path = sign_media_path(asset.id, ttl_seconds=ttl)
    except SignedUrlNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return MediaAccessUrl(url=path, expires_in_seconds=ttl)


@router.get("/public-media/{media_id}", include_in_schema=False)
def get_signed_public_media(
    media_id: UUID,
    expires: int,
    signature: str = Query(..., min_length=64, max_length=64),
    variant: str = Query(default="original", pattern="^original$"),
    db: DBSession = Depends(get_db),
) -> Response:
    if not verify_signature(media_id, variant=variant, expires=expires, signature=signature):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This media link is invalid or expired.")
    asset = db.query(MediaAsset).filter(MediaAsset.id == media_id, MediaAsset.archived.is_(False)).first()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media asset not found.")
    return _stream_file(asset, asset.storage_key, asset.mime_type)


@router.delete("/media-assets/{media_id}")
def archive_media_asset(
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, bool | str]:
    asset = _get_asset(db, current_user, media_id)
    membership = authorize_workspace(asset.workspace_id, current_user, db)
    if membership.role not in {"OWNER", "ADMIN"} and asset.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="Only the uploader or a workspace Owner/Admin can archive this asset.")
    asset.archived = True
    asset.deleted_at = datetime.now(timezone.utc)
    record_audit(
        db,
        action="media.archived",
        resource_type="media_asset",
        actor_user_id=current_user.id,
        workspace_id=asset.workspace_id,
        resource_id=asset.id,
    )
    db.commit()
    return {"id": str(asset.id), "archived": True}


# Draft attachments ---------------------------------------------------------


def _get_draft(db: DBSession, user: User, draft_id: UUID) -> ContentDraft:
    draft = db.query(ContentDraft).filter(ContentDraft.id == draft_id).first()
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found.")
    authorize_workspace(draft.project.workspace_id, user, db)
    return draft


def _set_draft_media(db: DBSession, user: User, draft: ContentDraft, media_ids: list[str], reason: str) -> list[str]:
    _ensure_project_editable(draft.project)
    valid_ids: list[str] = []
    for raw_id in media_ids:
        try:
            media_id = UUID(str(raw_id))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid media asset ID.") from exc
        asset = (
            db.query(MediaAsset)
            .filter(
                MediaAsset.id == media_id,
                MediaAsset.workspace_id == draft.project.workspace_id,
                MediaAsset.archived.is_(False),
            )
            .first()
        )
        if asset is None:
            raise HTTPException(status_code=404, detail=f"Media asset {raw_id} not found in this workspace.")
        valid_ids.append(str(asset.id))
    valid_ids = list(dict.fromkeys(valid_ids))
    if valid_ids != list(draft.media_asset_ids or []):
        draft.media_asset_ids = valid_ids
        # Media is part of the approved content: changing it creates a new
        # version and invalidates any existing approval (Phase 5 rules).
        ContentStudioService(db).create_version(draft, change_reason=reason, created_by=user.id)
        _mark_project_revised(draft.project)
        draft.updated_at = datetime.now(timezone.utc)
    db.commit()
    return list(draft.media_asset_ids or [])


@router.post("/content/drafts/{draft_id}/media", response_model=DraftMediaAttachment)
@router.put("/content/drafts/{draft_id}/media", response_model=DraftMediaAttachment)
def set_draft_media(
    draft_id: UUID,
    payload: DraftMediaAttachment,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> DraftMediaAttachment:
    """Replace the ordered list of attached media (attach, remove, or reorder)."""
    draft = _get_draft(db, current_user, draft_id)
    ids = _set_draft_media(db, current_user, draft, payload.media_asset_ids, "Media attachments updated")
    return DraftMediaAttachment(media_asset_ids=ids)


@router.delete("/content/drafts/{draft_id}/media/{media_id}", response_model=DraftMediaAttachment)
def remove_draft_media(
    draft_id: UUID,
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> DraftMediaAttachment:
    draft = _get_draft(db, current_user, draft_id)
    current = list(draft.media_asset_ids or [])
    if str(media_id) not in current:
        raise HTTPException(status_code=404, detail="This media asset is not attached to the draft.")
    _ensure_project_editable(draft.project)
    draft.media_asset_ids = [item for item in current if item != str(media_id)]
    ContentStudioService(db).create_version(draft, change_reason="Media attachment removed", created_by=current_user.id)
    _mark_project_revised(draft.project)
    db.commit()
    return DraftMediaAttachment(media_asset_ids=list(draft.media_asset_ids or []))


@router.get("/content/drafts/{draft_id}/media-preview", response_model=DraftPreview)
def preview_draft(
    draft_id: UUID,
    social_account_id: UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> DraftPreview:
    draft = _get_draft(db, current_user, draft_id)
    account = None
    if social_account_id is not None:
        account = (
            db.query(SocialAccount)
            .filter(SocialAccount.id == social_account_id, SocialAccount.workspace_id == draft.project.workspace_id)
            .first()
        )
        if account is None:
            raise HTTPException(status_code=404, detail="Social account not found in this workspace.")
    report = evaluate_eligibility(db, draft=draft, account=account, check_duplicates=account is not None)
    errors = report.errors
    if account is None:
        errors = [error for error in errors if error != "Select a connected social account."]
    prefix = get_settings().api_v1_prefix
    media = [
        PreviewMediaItem(
            id=asset.id,
            media_type=asset.mime_type.split("/")[0],
            mime_type=asset.mime_type,
            title=asset.title or asset.original_filename,
            width=asset.width,
            height=asset.height,
            duration_seconds=asset.duration_seconds,
            content_url=f"{prefix}/media-assets/{asset.id}/content",
            thumbnail_url=f"{prefix}/media-assets/{asset.id}/thumbnail" if asset.thumbnail_key else None,
        )
        for asset in report.media
    ]
    return DraftPreview(
        platform=draft.platform,
        preview_type=report.publish_format,
        supports_multiple_attachments=draft.platform in {"facebook", "instagram"},
        media_count=len(media),
        caption=report.caption,
        caption_length=len(report.caption),
        account_name=account.display_name if account else None,
        account_username=account.username if account else None,
        account_image_url=account.profile_image_url if account else None,
        media=media,
        errors=errors,
        warnings=report.warnings,
        attachment_names=[item.title for item in media],
    )
