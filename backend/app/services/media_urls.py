"""Expiring HMAC-signed media URLs.

Meta's publishing APIs fetch media from a public URL. Instead of making media
permanently public, Autowok issues short-lived signed URLs that only resolve a
single, non-archived asset until the expiry time.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from uuid import UUID

from app.core.config import get_settings


class SignedUrlNotConfigured(RuntimeError):
    pass


def _secret() -> bytes:
    secret = get_settings().media_url_signing_secret.strip()
    if len(secret) < 32:
        raise SignedUrlNotConfigured(
            "MEDIA_URL_SIGNING_SECRET must be set (32+ characters) to share media with Meta."
        )
    return secret.encode("utf-8")


def _signature(asset_id: UUID, expires: int, variant: str) -> str:
    message = f"{asset_id}:{expires}:{variant}".encode("ascii")
    return hmac.new(_secret(), message, hashlib.sha256).hexdigest()


def sign_media_path(asset_id: UUID, *, variant: str = "original", ttl_seconds: int | None = None) -> str:
    settings = get_settings()
    expires = int(time.time()) + (ttl_seconds or settings.media_signed_url_ttl_seconds)
    signature = _signature(asset_id, expires, variant)
    return f"{settings.api_v1_prefix}/public-media/{asset_id}?variant={variant}&expires={expires}&signature={signature}"


def public_media_url(asset_id: UUID, *, ttl_seconds: int | None = None) -> str:
    base = get_settings().public_media_base_url
    if not base:
        raise SignedUrlNotConfigured(
            "PUBLIC_MEDIA_BASE_URL must be a public HTTPS URL that Meta can reach to fetch media."
        )
    return f"{base}{sign_media_path(asset_id, ttl_seconds=ttl_seconds)}"


def verify_signature(asset_id: UUID, *, variant: str, expires: int, signature: str) -> bool:
    if expires < int(time.time()):
        return False
    try:
        expected = _signature(asset_id, expires, variant)
    except SignedUrlNotConfigured:
        return False
    return hmac.compare_digest(expected, signature)
