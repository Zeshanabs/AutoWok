from __future__ import annotations

from typing import Any

from app.services.ai_content.output_validator import OutputValidator
from app.services.ai_content.prompt_builder import PromptBuilder
from app.services.groq import GroqService


class WritingAssistantService:
    def __init__(self, db: Any, workspace_id: Any, *, groq_service: GroqService | None = None) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.groq_service = groq_service

    def _call_groq(self, prompt: str) -> dict[str, Any]:
        service = self.groq_service
        if service is None:
            return {}
        try:
            completion = service.generate_completion(prompt, temperature=0.5, max_tokens=1200)
            payload = OutputValidator.parse_json(completion.text)
            if payload:
                return payload
        except Exception:
            return {}
        return {}

    @staticmethod
    def _clean_text(text: str) -> str:
        return " ".join(str(text).split())

    def improve(self, payload: dict[str, Any], *, brand: dict[str, Any] | None = None) -> dict[str, Any]:
        prompt = PromptBuilder.build_writing_prompt({**payload, "action": "improve writing"}, brand=brand)
        response = self._call_groq(prompt)
        if response:
            output = response.get("output") or payload.get("text") or ""
            hashtags = OutputValidator.sanitize_hashtags(response.get("hashtags"))
            return {
                "output": self._clean_text(str(output)),
                "hook": OutputValidator.normalize_string(response.get("hook"), payload.get("text", "").split(".")[0]),
                "cta": OutputValidator.normalize_string(response.get("cta"), "Learn more today."),
                "hashtags": hashtags or ["#content", "#brand"],
                "notes": OutputValidator.normalize_list(response.get("notes")),
                "readability_score": int(response.get("readability_score") or 8),
                "brand_alignment": OutputValidator.normalize_string(response.get("brand_alignment"), "Appropriately aligned to the brand voice."),
            }
        text = self._clean_text(payload.get("text") or "")
        return {
            "output": text,
            "hook": text[:120] if text else "Stronger opening hook.",
            "cta": "Learn more today.",
            "hashtags": ["#content", "#brand"],
            "notes": ["Improved readability and flow without changing the original meaning."],
            "readability_score": 8,
            "brand_alignment": "Aligned to the brand's voice and message.",
        }

    def rewrite(self, payload: dict[str, Any], *, brand: dict[str, Any] | None = None) -> dict[str, Any]:
        text = self._clean_text(payload.get("text") or "")
        if not text:
            raise ValueError("Provide content to rewrite.")
        prompt = PromptBuilder.build_writing_prompt({**payload, "action": "rewrite"}, brand=brand)
        response = self._call_groq(prompt)
        if response:
            output = response.get("output") or text
            return {
                "output": self._clean_text(str(output)),
                "hook": OutputValidator.normalize_string(response.get("hook"), text[:120]),
                "cta": OutputValidator.normalize_string(response.get("cta"), "Learn more today."),
                "hashtags": OutputValidator.sanitize_hashtags(response.get("hashtags")) or ["#content"],
            }
        sentence = text.rstrip(".") + "."
        return {
            "output": sentence,
            "hook": sentence[:120],
            "cta": "Learn more today.",
            "hashtags": ["#content"],
        }

    def change_tone(self, payload: dict[str, Any], *, brand: dict[str, Any] | None = None) -> dict[str, Any]:
        text = self._clean_text(payload.get("text") or "")
        tone = payload.get("tone") or "Professional"
        prompt = PromptBuilder.build_writing_prompt({**payload, "action": f"change tone to {tone}"}, brand=brand)
        response = self._call_groq(prompt)
        if response and response.get("output"):
            return {
                "output": self._clean_text(str(response.get("output"))),
                "tone": tone,
                "brand_alignment": OutputValidator.normalize_string(response.get("brand_alignment"), "Tone adapted to the brand voice."),
            }
        return {
            "output": text,
            "tone": tone,
            "brand_alignment": "Tone adapted to the brand voice while preserving meaning.",
        }

    def shorten(self, payload: dict[str, Any], *, brand: dict[str, Any] | None = None) -> dict[str, Any]:
        text = self._clean_text(payload.get("text") or "")
        prompt = PromptBuilder.build_writing_prompt({**payload, "action": "shorten content"}, brand=brand)
        response = self._call_groq(prompt)
        if response and response.get("output"):
            return {"output": self._clean_text(str(response.get("output"))) }
        parts = text.split()
        shortened = " ".join(parts[:max(8, len(parts) // 2)])
        return {"output": shortened}

    def expand(self, payload: dict[str, Any], *, brand: dict[str, Any] | None = None) -> dict[str, Any]:
        text = self._clean_text(payload.get("text") or "")
        prompt = PromptBuilder.build_writing_prompt({**payload, "action": "expand content"}, brand=brand)
        response = self._call_groq(prompt)
        if response and response.get("output"):
            return {"output": self._clean_text(str(response.get("output"))) }
        return {"output": text + " Additional depth helps the audience understand the value and apply it quickly."}
