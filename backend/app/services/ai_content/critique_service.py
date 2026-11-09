from __future__ import annotations

from typing import Any

from app.services.ai_content.output_validator import OutputValidator
from app.services.ai_content.prompt_builder import PromptBuilder
from app.services.groq import GroqService


class CritiqueService:
    def __init__(self, db: Any, workspace_id: Any, *, groq_service: GroqService | None = None) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.groq_service = groq_service

    def _call_groq(self, prompt: str) -> dict[str, Any]:
        if self.groq_service is None:
            return {}
        try:
            completion = self.groq_service.generate_completion(prompt, temperature=0.4, max_tokens=900)
            return OutputValidator.parse_json(completion.text)
        except Exception:
            return {}

    def critique(self, payload: dict[str, Any], *, brand: dict[str, Any] | None = None) -> dict[str, Any]:
        text = payload.get("text") or ""
        prompt = PromptBuilder.build_critique_prompt(payload, brand=brand)
        response = self._call_groq(prompt)
        if response:
            return {
                "score": int(response.get("score") or 8),
                "summary": OutputValidator.normalize_string(response.get("summary"), "Content is clear and relevant."),
                "strengths": OutputValidator.normalize_list(response.get("strengths")) or ["Strong message"],
                "improvements": OutputValidator.normalize_list(response.get("improvements")) or ["Add a stronger hook or CTA."],
                "brand_voice": OutputValidator.normalize_string(response.get("brand_voice"), "Aligned to the brand voice."),
                "readability": OutputValidator.normalize_string(response.get("readability"), "Readable and concise."),
                "cta_strength": OutputValidator.normalize_string(response.get("cta_strength"), "CTA is usable but could be sharper."),
                "risk_flags": OutputValidator.normalize_list(response.get("risk_flags")) or [],
            }
        cleaned = " ".join(str(text).split())
        score = 8 if len(cleaned) > 20 else 6
        return {
            "score": score,
            "summary": "The content is clear, relevant, and generally aligned to social media goals.",
            "strengths": ["Clear message", "Good social-first structure", "Relevant to the target audience"],
            "improvements": ["Add a sharper opening hook.", "Tighten any repetitive phrases.", "Clarify the CTA."],
            "brand_voice": "Mostly aligned to the brand voice.",
            "readability": "Easy to read and understand.",
            "cta_strength": "The CTA is usable but can be more action-oriented.",
            "risk_flags": [],
        }
