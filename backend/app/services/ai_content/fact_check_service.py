from __future__ import annotations

from typing import Any

from app.services.ai_content.output_validator import OutputValidator
from app.services.ai_content.prompt_builder import PromptBuilder
from app.services.groq import GroqService


class FactCheckService:
    def __init__(self, db: Any, workspace_id: Any, *, groq_service: GroqService | None = None) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.groq_service = groq_service

    def _call_groq(self, prompt: str) -> dict[str, Any]:
        if self.groq_service is None:
            return {}
        try:
            completion = self.groq_service.generate_completion(prompt, temperature=0.2, max_tokens=900)
            return OutputValidator.parse_json(completion.text)
        except Exception:
            return {}

    def fact_check(self, payload: dict[str, Any], *, research: dict[str, Any] | None = None) -> dict[str, Any]:
        claims = payload.get("claims") or []
        prompt = PromptBuilder.build_fact_check_prompt(payload, research=research)
        response = self._call_groq(prompt)
        if response.get("claims"):
            normalized = []
            for claim in response.get("claims"):
                if not isinstance(claim, dict):
                    continue
                normalized.append({
                    "claim": OutputValidator.normalize_string(claim.get("claim"), "Claim not provided."),
                    "status": OutputValidator.normalize_string(claim.get("status"), "unclear"),
                    "reasoning": OutputValidator.normalize_string(claim.get("reasoning"), "No evidence provided."),
                    "evidence": OutputValidator.normalize_list(claim.get("evidence")),
                })
            return {"claims": normalized, "overall_verdict": OutputValidator.normalize_string(response.get("overall_verdict"), "Review the evidence before publishing."), "workspace_id": str(self.workspace_id)}

        normalized = []
        for claim in claims:
            normalized.append({
                "claim": str(claim),
                "status": "unclear",
                "reasoning": "No supporting research evidence was supplied for this claim.",
                "evidence": OutputValidator.normalize_list((research or {}).get("references")),
            })
        return {
            "claims": normalized,
            "overall_verdict": "No specific evidence was provided to verify these claims, so the content should be reviewed before publication.",
            "workspace_id": str(self.workspace_id),
        }
