from __future__ import annotations

import re
import uuid

from email_validator import validate_email


def normalize_email(email: str) -> str:
    return validate_email(email.strip(), check_deliverability=False).normalized.casefold()


def generate_workspace_slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "workspace"
    return f"{base[:100]}-{uuid.uuid4().hex[:8]}"
