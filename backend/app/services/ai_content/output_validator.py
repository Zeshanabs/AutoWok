from __future__ import annotations

import json
import re
from typing import Any


class OutputValidator:
    @staticmethod
    def parse_json(raw: str | None) -> dict[str, Any]:
        if raw is None:
            return {}
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```\s*$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def sanitize_hashtags(values: Any) -> list[str]:
        if not isinstance(values, list):
            values = [values] if values else []
        result: list[str] = []
        for item in values:
            text = str(item).strip()
            if not text:
                continue
            if not text.startswith("#"):
                text = f"#{text.lstrip('#')}"
            result.append(text)
        return result[:10]

    @staticmethod
    def normalize_string(value: Any, fallback: str = "") -> str:
        if value is None:
            return fallback
        text = str(value).strip()
        return text or fallback

    @staticmethod
    def normalize_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            items = value
        else:
            items = [value]
        normalized = []
        for item in items:
            text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized

    @staticmethod
    def require_keys(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
        for key in keys:
            payload.setdefault(key, "")
        return payload
