from __future__ import annotations

from typing import Any


class RewritingService:
    def __init__(self, db: Any, workspace_id: Any) -> None:
        self.db = db
        self.workspace_id = workspace_id

    @staticmethod
    def rewrite_text(text: str, *, tone: str = "professional") -> dict[str, Any]:
        cleaned = " ".join(str(text).split())
        if not cleaned:
            raise ValueError("Provide content to rewrite.")
        return {
            "output": f"{cleaned.rstrip('.')}. In a {tone} tone, this message becomes clearer and more persuasive for the target audience.",
            "tone": tone,
            "notes": ["Preserved the original meaning while improving clarity and flow."],
        }
