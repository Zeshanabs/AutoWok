from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings


class EncryptionNotConfigured(RuntimeError):
    pass


def _fernet() -> MultiFernet:
    settings = get_settings()
    if not settings.ai_encryption_key.strip():
        raise EncryptionNotConfigured(
            "AI credential encryption is not configured. Set AI_ENCRYPTION_KEY."
        )
    key_values = [
        value.strip()
        for value in (settings.ai_encryption_key, settings.ai_encryption_key_previous)
        if value.strip()
    ]
    try:
        return MultiFernet([Fernet(value.encode("ascii")) for value in key_values])
    except (ValueError, UnicodeEncodeError) as exc:
        raise EncryptionNotConfigured(
            "AI_ENCRYPTION_KEY must be a URL-safe base64 Fernet key."
        ) from exc


def encrypt_api_key(api_key: str) -> str:
    if not api_key or not api_key.strip():
        raise ValueError("An API key is required.")
    try:
        return _fernet().encrypt(api_key.encode("utf-8")).decode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("The API key must be valid Unicode text.") from exc


def decrypt_api_key(encrypted_api_key: str) -> str:
    try:
        return _fernet().decrypt(encrypted_api_key.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise EncryptionNotConfigured(
            "The stored provider credential cannot be decrypted with the configured keys."
        ) from exc


def rotate_api_key(encrypted_api_key: str) -> str:
    try:
        return _fernet().rotate(encrypted_api_key.encode("ascii")).decode("ascii")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise EncryptionNotConfigured(
            "The stored provider credential cannot be decrypted with the configured keys."
        ) from exc
