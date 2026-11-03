from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import AIProviderConfig, MetaAuthorization, SocialAccountCredential
from app.services.ai_encryption import rotate_api_key
from app.services.token_encryption import rotate_token


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-encrypt stored credentials using the configured primary key."
    )
    parser.add_argument(
        "--scope",
        choices=("meta", "ai", "all"),
        required=True,
        help="Credential family to rotate.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify decryption and report counts without writing changes.",
    )
    args = parser.parse_args()
    settings = get_settings()

    if args.scope in {"meta", "all"} and (
        not settings.meta_token_encryption_key.strip()
        or not settings.meta_token_encryption_key_previous.strip()
        or settings.meta_token_encryption_key.strip()
        == settings.meta_token_encryption_key_previous.strip()
    ):
        parser.error(
            "Meta rotation requires a new TOKEN_ENCRYPTION_KEY and a distinct "
            "TOKEN_ENCRYPTION_KEY_PREVIOUS."
        )
    if args.scope in {"ai", "all"} and (
        not settings.ai_encryption_key.strip()
        or not settings.ai_encryption_key_previous.strip()
        or settings.ai_encryption_key.strip() == settings.ai_encryption_key_previous.strip()
    ):
        parser.error(
            "AI rotation requires a new AI_ENCRYPTION_KEY and a distinct "
            "AI_ENCRYPTION_KEY_PREVIOUS."
        )

    counts = {"meta_authorizations": 0, "social_credentials": 0, "ai_providers": 0}
    db = SessionLocal()
    try:
        if args.scope in {"meta", "all"}:
            for record in db.query(MetaAuthorization).yield_per(100):
                record.encrypted_user_access_token = rotate_token(
                    record.encrypted_user_access_token
                )
                counts["meta_authorizations"] += 1
            for record in db.query(SocialAccountCredential).yield_per(100):
                record.encrypted_access_token = rotate_token(record.encrypted_access_token)
                if record.encrypted_refresh_token:
                    record.encrypted_refresh_token = rotate_token(
                        record.encrypted_refresh_token
                    )
                counts["social_credentials"] += 1
        if args.scope in {"ai", "all"}:
            for record in db.query(AIProviderConfig).yield_per(100):
                record.encrypted_api_key = rotate_api_key(record.encrypted_api_key)
                counts["ai_providers"] += 1

        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    action = "Verified (dry run)" if args.dry_run else "Rotated"
    print(
        f"{action}: {counts['meta_authorizations']} Meta authorizations, "
        f"{counts['social_credentials']} social credentials, "
        f"{counts['ai_providers']} AI provider keys."
    )


if __name__ == "__main__":
    main()
