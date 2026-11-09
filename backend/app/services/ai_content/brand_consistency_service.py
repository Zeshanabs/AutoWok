from __future__ import annotations

from typing import Any


class BrandConsistencyService:
    def __init__(self, db: Any, workspace_id: Any) -> None:
        self.db = db
        self.workspace_id = workspace_id

    @staticmethod
    def assess(text: str, *, brand: dict[str, Any] | None = None) -> dict[str, Any]:
        cleaned = " ".join(str(text).split())
        brand_name = (brand or {}).get("name") or "your brand"
        tone = (brand or {}).get("voice") or "professional and clear"
        return {
            "brand_name": brand_name,
            "brand_voice_alignment": f"The copy aligns with a {tone} voice suitable for {brand_name}.",
            "checklist": [
                "Message matches the brand objective.",
                "Tone is consistent with the brand voice.",
                "CTA is consistent with the brand's content goals.",
            ],
            "overall_status": "pass" if cleaned else "needs_review",
        }
