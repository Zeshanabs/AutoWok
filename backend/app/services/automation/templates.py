"""Safe text templates for notification titles, messages and task names.

Only ``{field_name}`` placeholders that name a field of the trigger's payload
schema are substituted. There is no expression evaluation, attribute access,
formatting spec or code execution: the template is scanned with a regular
expression and each known placeholder is replaced by the stringified value.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.automation.registry import TriggerSpec

PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
MAX_VALUE_LENGTH = 200


def placeholders(text: str) -> list[str]:
    return PLACEHOLDER.findall(text or "")


def unknown_placeholders(spec: TriggerSpec, text: str | None) -> list[str]:
    known = spec.field_map()
    return sorted({name for name in placeholders(text or "") if name not in known})


def render(text: str | None, payload: dict[str, Any]) -> str:
    if not text:
        return ""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in payload:
            return match.group(0)
        value = payload[name]
        if value is None:
            return "—"
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value) or "—"
        return str(value)[:MAX_VALUE_LENGTH]

    return PLACEHOLDER.sub(replace, text)
