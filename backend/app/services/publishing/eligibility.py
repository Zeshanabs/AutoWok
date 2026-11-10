"""Publishing eligibility and platform-format validation.

This is the single source of truth used by the preview endpoint, the
immediate-publish endpoint, the background worker (revalidation before the
Meta call), and scheduling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.models import ContentDraft, ContentProject, ContentPublication, MediaAsset, SocialAccount
from app.models.content import ACTIVE_PUBLICATION_STATUSES
from app.services.content_studio import ContentStudioService
from app.services.meta_graph import (
    FACEBOOK_PUBLISH_SCOPES,
    FACEBOOK_VIDEO_SCOPES,
    INSTAGRAM_PUBLISH_SCOPES,
)
from app.services.storage import storage_service

PLATFORM_ACCOUNT_TYPES = {"facebook": "facebook_page", "instagram": "instagram"}
INSTAGRAM_ELIGIBLE_ACCOUNT_TYPES = {"BUSINESS", "MEDIA_CREATOR"}
INSTAGRAM_MAX_CAROUSEL = 20
FACEBOOK_MAX_PHOTOS = 10
INSTAGRAM_CAPTION_LIMIT = 2200
INSTAGRAM_HASHTAG_LIMIT = 30


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def compose_caption(draft: ContentDraft) -> str:
    parts = [str(part).strip() for part in (draft.hook, draft.body, draft.cta) if part and str(part).strip()]
    hashtags = " ".join(tag.strip() for tag in (draft.hashtags or []) if tag and tag.strip())
    if hashtags:
        parts.append(hashtags)
    return "\n\n".join(parts)


def publication_guard(draft_id: UUID, social_account_id: UUID) -> str:
    return f"{draft_id}:{social_account_id}"


@dataclass
class EligibilityReport:
    platform: str
    publish_format: str | None = None
    caption: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    media: list[MediaAsset] = field(default_factory=list)
    approval_status: str | None = None
    content_version_number: int | None = None

    @property
    def eligible(self) -> bool:
        return not self.errors


def _determine_format(platform: str, media: list[MediaAsset], report: EligibilityReport) -> None:
    images = [asset for asset in media if asset.mime_type.startswith("image/")]
    videos = [asset for asset in media if asset.mime_type.startswith("video/")]
    if platform == "facebook":
        if not media:
            report.publish_format = "text"
        elif len(media) == 1 and videos:
            report.publish_format = "video"
        elif videos:
            report.errors.append("Facebook Page posts cannot mix a video with other media. Attach one video or only images.")
        elif len(images) == 1:
            report.publish_format = "photo"
        elif len(images) <= FACEBOOK_MAX_PHOTOS:
            report.publish_format = "multi_photo"
        else:
            report.errors.append(f"Facebook multi-photo posts support at most {FACEBOOK_MAX_PHOTOS} images.")
        return

    if not media:
        report.errors.append("Instagram posts require at least one image or video.")
        return
    if len(media) > INSTAGRAM_MAX_CAROUSEL:
        report.errors.append(f"Instagram carousels support at most {INSTAGRAM_MAX_CAROUSEL} items.")
        return
    non_jpeg = [asset.title or asset.original_filename for asset in images if asset.mime_type != "image/jpeg"]
    if non_jpeg:
        report.errors.append(
            "Instagram publishing accepts JPEG images only. Replace: " + ", ".join(non_jpeg) + "."
        )
    for asset in images:
        if asset.width and asset.height:
            ratio = asset.width / asset.height
            if ratio < 0.8 - 0.005 or ratio > 1.91 + 0.005:
                report.warnings.append(
                    f"{asset.title or asset.original_filename} has an aspect ratio outside 4:5–1.91:1 and may be rejected or cropped by Instagram."
                )
    for asset in videos:
        if asset.duration_seconds is not None and not 3 <= asset.duration_seconds <= 900:
            report.warnings.append(
                f"{asset.title or asset.original_filename} is outside the 3 second to 15 minute range Instagram supports for Reels."
            )
    if len(media) == 1:
        report.publish_format = "reel" if videos else "image"
    else:
        report.publish_format = "carousel"
        if any(asset.width and asset.height and abs(asset.width / asset.height - (media[0].width or 1) / (media[0].height or 1)) > 0.01 for asset in images if media[0].width and media[0].height):
            report.warnings.append("Instagram crops every carousel item to the aspect ratio of the first item.")


def evaluate_eligibility(
    db: DBSession,
    *,
    draft: ContentDraft,
    account: SocialAccount | None,
    exclude_publication_id: UUID | None = None,
    check_duplicates: bool = True,
    expected_version: int | None = None,
    exclude_schedule_id: UUID | None = None,
) -> EligibilityReport:
    project: ContentProject = draft.project
    platform = draft.platform
    report = EligibilityReport(platform=platform, approval_status=project.status, content_version_number=draft.version_count)
    settings = get_settings()

    # 1. Approval (Phase 5 workflow). Edits after approval reset the project
    # to draft, so an approved status always refers to the current version.
    if project.status != "approved" or draft.status != "approved":
        report.errors.append("Only approved content can be published. Submit the project for approval first.")
    if expected_version is not None and draft.version_count != expected_version:
        report.errors.append("The content changed after this job was created. The approved version no longer applies.")

    # 2. Account checks.
    if account is None:
        report.errors.append("Select a connected social account.")
    else:
        if account.workspace_id != project.workspace_id:
            report.errors.append("The social account does not belong to this workspace.")
        expected_type = PLATFORM_ACCOUNT_TYPES.get(platform)
        if expected_type is None:
            report.errors.append("This draft's platform is not supported for publishing.")
        elif account.platform != expected_type:
            report.errors.append(
                f"A {platform} draft can only be published to a {'Facebook Page' if expected_type == 'facebook_page' else 'Instagram Professional account'}."
            )
        if account.connection_status != "connected":
            report.errors.append(
                f"The account is {account.connection_status}. Reconnect it in Social account settings."
            )
        credential = account.credential
        if credential is None:
            report.errors.append("The account has no stored credential. Reconnect it.")
        elif _utc(credential.access_token_expires_at) and _utc(credential.access_token_expires_at) <= datetime.now(timezone.utc):
            report.errors.append("The account access token has expired. Reconnect the account.")
        if account.platform == "instagram" and account.account_type not in INSTAGRAM_ELIGIBLE_ACCOUNT_TYPES:
            report.errors.append("Only Instagram Business or Creator (Professional) accounts can publish through the API.")
        if project.brand_id and account.brand_id and project.brand_id != account.brand_id:
            report.warnings.append("This account is assigned to a different brand than the content project.")

    # 3. Content checks.
    validation = ContentStudioService(db).platform_validation(
        platform,
        {"title": draft.title, "hook": draft.hook, "body": draft.body, "cta": draft.cta, "hashtags": draft.hashtags},
    )
    report.errors.extend(validation["errors"])
    report.warnings.extend(validation["warnings"])
    report.caption = compose_caption(draft)
    if platform == "instagram" and len(report.caption) > INSTAGRAM_CAPTION_LIMIT:
        report.errors.append("The Instagram caption including hashtags exceeds 2,200 characters.")

    # 4. Media checks.
    media: list[MediaAsset] = []
    for raw_id in draft.media_asset_ids or []:
        try:
            media_id = UUID(str(raw_id))
        except ValueError:
            report.errors.append("An attached media reference is invalid. Re-attach the media.")
            continue
        asset = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
        if asset is None or asset.workspace_id != project.workspace_id:
            report.errors.append("An attached media asset no longer exists in this workspace.")
            continue
        label = asset.title or asset.original_filename
        if asset.archived:
            report.errors.append(f"{label} was archived. Remove it or restore a different asset.")
            continue
        if asset.processing_status != "ready":
            report.errors.append(f"{label} is not ready ({asset.processing_status}).")
            continue
        if not storage_service.exists(asset.storage_key):
            report.errors.append(f"The stored file for {label} is missing. Upload it again.")
            continue
        media.append(asset)
    report.media = media
    _determine_format(platform, media, report)

    if media and (not settings.public_media_base_url or len(settings.media_url_signing_secret.strip()) < 32):
        report.errors.append(
            "Publishing media requires PUBLIC_MEDIA_BASE_URL (a public HTTPS address Meta can reach) and "
            "MEDIA_URL_SIGNING_SECRET to be configured on the server."
        )

    # 5. Permissions recorded at connection time.
    if account is not None:
        scopes = set(account.granted_scopes or [])
        if account.platform == "facebook_page":
            required = set(FACEBOOK_PUBLISH_SCOPES)
            if report.publish_format == "video":
                required |= set(FACEBOOK_VIDEO_SCOPES)
        else:
            required = set(INSTAGRAM_PUBLISH_SCOPES)
        missing = sorted(required - scopes)
        if missing:
            report.errors.append(
                "The account is missing Meta permissions required for publishing: "
                + ", ".join(missing)
                + ". Reconnect Meta and grant them."
            )

    # 6. Duplicate prevention.
    if check_duplicates and account is not None:
        query = db.query(ContentPublication).filter(
            ContentPublication.draft_id == draft.id,
            ContentPublication.social_account_id == account.id,
            or_(
                ContentPublication.status.in_(("published", *ACTIVE_PUBLICATION_STATUSES)),
                ContentPublication.active_guard.is_not(None),
            ),
        )
        if exclude_publication_id is not None:
            query = query.filter(ContentPublication.id != exclude_publication_id)
        existing = query.first()
        if existing is not None:
            if existing.status == "published":
                report.errors.append("This content was already published to this account.")
            elif existing.status == "failed":
                report.errors.append(
                    "A previous publishing job for this account has an unconfirmed result. Resolve it from "
                    "the publishing history before publishing again."
                )
            else:
                report.errors.append("A publishing job for this content and account is already in progress.")
        from app.models.scheduling import ACTIVE_SCHEDULE_STATUSES, ScheduledPost

        schedule_query = db.query(ScheduledPost).filter(
            ScheduledPost.draft_id == draft.id,
            ScheduledPost.social_account_id == account.id,
            ScheduledPost.status.in_(ACTIVE_SCHEDULE_STATUSES),
        )
        if exclude_schedule_id is not None:
            schedule_query = schedule_query.filter(ScheduledPost.id != exclude_schedule_id)
        if exclude_publication_id is not None:
            schedule_query = schedule_query.filter(
                or_(ScheduledPost.publication_id.is_(None), ScheduledPost.publication_id != exclude_publication_id)
            )
        if schedule_query.first() is not None:
            report.errors.append(
                "This content is already scheduled for this account. Edit or cancel that schedule instead."
            )
    return report
