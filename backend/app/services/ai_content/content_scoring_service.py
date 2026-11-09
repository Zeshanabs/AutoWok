from __future__ import annotations

from typing import Any


class ContentScoringService:
    def __init__(self, db: Any, workspace_id: Any) -> None:
        self.db = db
        self.workspace_id = workspace_id

    @staticmethod
    def score(text: str, *, objective: str | None = None) -> dict[str, Any]:
        cleaned = " ".join(str(text).split())
        words = len(cleaned.split()) if cleaned else 0
        score = 8 if words > 25 else 6
        return {
            "score": score,
            "objective": objective or "engagement",
            "readability": "Readable and concise." if score >= 7 else "Needs tighter phrasing.",
        }
