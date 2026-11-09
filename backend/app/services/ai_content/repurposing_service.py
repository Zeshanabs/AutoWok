from __future__ import annotations

from typing import Any


class RepurposingService:
    def __init__(self, db: Any, workspace_id: Any) -> None:
        self.db = db
        self.workspace_id = workspace_id

    @staticmethod
    def repurpose(text: str, *, platform: str = "instagram") -> dict[str, Any]:
        cleaned = " ".join(str(text).split())
        if not cleaned:
            raise ValueError("Provide content to repurpose.")
        platform_map = {
            "instagram": "a short vertical caption and a simple hook",
            "facebook": "a more conversational post with a clear CTA",
            "linkedin": "a professional take with a credibility angle",
        }
        return {
            "output": f"Repurposed for {platform}: {cleaned[:200]} {platform_map.get(platform, 'a concise social version')}",
            "platform": platform,
            "variants": [
                "Short-form version",
                "Long-form version",
                "Carousel version",
            ],
        }
