from __future__ import annotations

from typing import Any


class HookGenerationService:
    def __init__(self, db: Any, workspace_id: Any) -> None:
        self.db = db
        self.workspace_id = workspace_id

    @staticmethod
    def generate(topic: str, *, objective: str | None = None) -> dict[str, Any]:
        clean_topic = " ".join(str(topic).split())
        objective_text = objective or "drive action"
        return {
            "hooks": [
                f"Here’s the one thing people get wrong about {clean_topic}.",
                f"If you want better results from {clean_topic}, start here.",
                f"This is why {clean_topic} matters more than most brands realize.",
            ],
            "recommended_cta": f"Learn how to make {objective_text.lower()} with confidence.",
        }
