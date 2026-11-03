from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings


class TokenEncryptionNotConfigured(RuntimeError):
    pass


def _fernet() -> MultiFernet:
    settings = get_settings()
    if not settings.meta_token_encryption_key.strip():
        raise TokenEncryptionNotConfigured(
            "Social token encryption is not configured. Set TOKEN_ENCRYPTION_KEY."
        )
    values = [
        value.strip()
        for value in (
            settings.meta_token_encryption_key,
            settings.meta_token_encryption_key_previous,
        )
        if value.strip()
    ]
    try:
        return MultiFernet([Fernet(value.encode("ascii")) for value in values])
    except (ValueError, UnicodeEncodeError) as exc:
        raise TokenEncryptionNotConfigured(
            "TOKEN_ENCRYPTION_KEY must be a URL-safe base64 Fernet key."
        ) from exc


def encrypt_token(token: str) -> str:
    if not token or not token.strip():
        raise ValueError("A non-empty access token is required.")
    try:
        return _fernet().encrypt(token.encode("utf-8")).decode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("The token must be valid Unicode text.") from exc


def decrypt_token(encrypted_token: str) -> str:
    try:
        return _fernet().decrypt(encrypted_token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise TokenEncryptionNotConfigured(
            "The stored social credential cannot be decrypted with the configured keys."
        ) from exc


def rotate_token(encrypted_token: str) -> str:
    try:
        return _fernet().rotate(encrypted_token.encode("ascii")).decode("ascii")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise TokenEncryptionNotConfigured(
            "The stored social credential cannot be decrypted with the configured keys."
        ) from exc
