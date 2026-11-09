from __future__ import annotations

import hashlib
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DBSession

from app.api.v1.dependencies.auth import get_current_user
from app.db.session import get_db
from app.models import Brand, ContentDraft, MediaAsset, User, WorkspaceMembership
from app.models.content import ContentProject
from app.schemas.media_assets import DraftMediaAttachment, DraftPreview, MediaAssetRead
from app.services.storage import storage_service

router = APIRouter(tags=["media assets"])

ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "audio/mpeg",
    "audio/mp4",
    "audio/wav",
}


def _workspace_membership(db: DBSession, user: User, workspace_id: UUID) -> WorkspaceMembership:
    membership = (
        db.query(WorkspaceMembership)
        .filter(WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.user_id == user.id)
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    return membership


def _media_asset_read(asset: MediaAsset) -> MediaAssetRead:
    read = MediaAssetRead.model_validate(asset)
    read.download_url = f"/api/v1/media-assets/{asset.id}/download"
    read.thumbnail_url = (
        f"/api/v1/media-assets/{asset.id}/thumbnail" if asset.thumbnail_key else None
    )
    return read


@router.get("/media-assets", response_model=list[MediaAssetRead])
def list_media_assets(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[MediaAssetRead]:
    _workspace_membership(db, current_user, workspace_id)
    assets = (
        db.query(MediaAsset)
        .filter(MediaAsset.workspace_id == workspace_id, MediaAsset.archived.is_(False))
        .order_by(MediaAsset.created_at.desc())
        .all()
    )
    return [_media_asset_read(asset) for asset in assets]


@router.get("/media-assets/{media_id}", response_model=MediaAssetRead)
def get_media_asset(
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> MediaAssetRead:
    asset = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media asset not found.")
    _workspace_membership(db, current_user, asset.workspace_id)
    return _media_asset_read(asset)


@router.post("/media-assets/upload", response_model=MediaAssetRead, status_code=status.HTTP_201_CREATED)
async def upload_media_asset(
    workspace_id: UUID = Form(...),
    brand_id: UUID | None = Form(default=None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> MediaAssetRead:
    _workspace_membership(db, current_user, workspace_id)
    if brand_id is not None:
        brand = db.query(Brand).filter(Brand.id == brand_id, Brand.workspace_id == workspace_id).first()
        if brand is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brand not found in this workspace.")

    if file.filename is None or not file.filename.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A file name is required.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded file is empty.")

    mime_type = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported media type. Allowed: images, MP4/QuickTime/WebM video, and common audio files.",
        )

    checksum = hashlib.sha256(file_bytes).hexdigest()
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
        return _media_asset_read(existing_asset)

    suffix = Path(file.filename).suffix.lower()
    storage_key = f"workspaces/{workspace_id}/media/{uuid4()}{suffix or ''}"
    storage_service.save_file(storage_key, file_bytes)

    asset = MediaAsset(
        workspace_id=workspace_id,
        brand_id=brand_id,
        original_filename=file.filename,
        storage_key=storage_key,
        mime_type=mime_type,
        file_extension=suffix.lstrip("."),
        file_size=len(file_bytes),
        checksum=checksum,
        uploaded_by=current_user.id,
        processing_status="ready",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _media_asset_read(asset)


@router.get("/media-assets/{media_id}/download")
def download_media_asset(
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    asset = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if asset is None or asset.archived:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media asset not found.")
    _workspace_membership(db, current_user, asset.workspace_id)

    file_path = storage_service.resolve_path(asset.storage_key)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored media file not found.")

    return FileResponse(path=file_path, media_type=asset.mime_type, filename=asset.original_filename)


@router.get("/media-assets/{media_id}/thumbnail")
def get_media_asset_thumbnail(
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    asset = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if asset is None or asset.archived:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media asset not found.")
    _workspace_membership(db, current_user, asset.workspace_id)

    if not asset.thumbnail_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail not generated.")

    file_path = storage_service.resolve_path(asset.thumbnail_key)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail file not found.")

    return FileResponse(path=file_path, media_type=asset.mime_type, filename=f"{asset.id}-thumb")


@router.delete("/media-assets/{media_id}")
def archive_media_asset(
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, bool | str]:
    asset = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media asset not found.")
    _workspace_membership(db, current_user, asset.workspace_id)

    asset.archived = True
    asset.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": str(asset.id), "archived": True}


@router.post("/content/drafts/{draft_id}/media", response_model=DraftMediaAttachment)
def attach_media_to_draft(
    draft_id: UUID,
    payload: DraftMediaAttachment,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> DraftMediaAttachment:
    draft = db.query(ContentDraft).filter(ContentDraft.id == draft_id).first()
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found.")

    project = db.query(ContentProject).filter(ContentProject.id == draft.project_id).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content project not found.")
    _workspace_membership(db, current_user, project.workspace_id)

    valid_ids: list[str] = []
    for asset_id in payload.media_asset_ids:
        media_id = UUID(asset_id)
        asset = (
            db.query(MediaAsset)
            .filter(
                MediaAsset.id == media_id,
                MediaAsset.workspace_id == project.workspace_id,
                MediaAsset.archived.is_(False),
            )
            .first()
        )
        if asset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Media asset {asset_id} not found in this workspace.",
            )
        valid_ids.append(str(asset.id))

    draft.media_asset_ids = list(dict.fromkeys(valid_ids))
    db.commit()
    return DraftMediaAttachment(media_asset_ids=draft.media_asset_ids)


@router.get("/content/drafts/{draft_id}/media-preview", response_model=DraftPreview)
def preview_draft_media(
    draft_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> DraftPreview:
    draft = db.query(ContentDraft).filter(ContentDraft.id == draft_id).first()
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found.")

    project = db.query(ContentProject).filter(ContentProject.id == draft.project_id).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content project not found.")
    _workspace_membership(db, current_user, project.workspace_id)

    alts = []
    if draft.media_asset_ids:
        assets = (
            db.query(MediaAsset)
            .filter(
                MediaAsset.id.in_([UUID(asset_id) for asset_id in draft.media_asset_ids]),
                MediaAsset.workspace_id == project.workspace_id,
                MediaAsset.archived.is_(False),
            )
            .all()
        )
        alts = [asset.original_filename for asset in assets]

    warnings: list[str] = []
    if draft.platform.lower() in {"facebook", "instagram"} and len(alts) > 1:
        warnings.append("Carousel-style previews are approximate and should be validated before publishing.")

    return DraftPreview(
        platform=draft.platform,
        preview_type="carousel" if len(alts) > 1 else "single_post",
        approximate=True,
        supports_multiple_attachments=draft.platform.lower() in {"facebook", "instagram"},
        media_count=len(alts),
        caption=draft.body or draft.hook,
        warnings=warnings,
        attachment_names=alts,
    )
