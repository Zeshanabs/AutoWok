from __future__ import annotations

from typing import Any


class HashtagService:
    def __init__(self, db: Any, workspace_id: Any) -> None:
        self.db = db
        self.workspace_id = workspace_id

    @staticmethod
    def recommend(topic: str, *, platform: str = "instagram") -> dict[str, Any]:
        clean_topic = " ".join(str(topic).split()).replace(" ", "")
        tags = [
            f"#{clean_topic.lower()}",
            "#contentstrategy",
            "#brandgrowth",
            "#socialmedia",
        ]
        if platform == "linkedin":
            tags = ["#linkedinmarketing", "#thoughtleadership", "#brandstory"]
        return {"hashtags": tags[:10], "platform": platform}
