from __future__ import annotations

from typing import Any

from app.services.ai_content.output_validator import OutputValidator
from app.services.ai_content.prompt_builder import PromptBuilder
from app.services.groq import GroqService


class IdeationService:
    def __init__(self, db: Any, workspace_id: Any, *, groq_service: GroqService | None = None) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.groq_service = groq_service

    def _call_groq(self, prompt: str, *, temperature: float = 0.7, max_tokens: int = 1200) -> dict[str, Any]:
        service = self.groq_service
        if service is None:
            return {}
        try:
            completion = service.generate_completion(prompt, temperature=temperature, max_tokens=max_tokens)
            payload = OutputValidator.parse_json(completion.text)
            if payload:
                return payload
        except Exception:
            return {}
        return {}

    def _fallback_ideas(self, payload: dict[str, Any], brand: dict[str, Any] | None = None, research: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        topic = payload.get("topic") or "brand growth"
        objective = payload.get("objective") or "increase engagement and awareness"
        platform = payload.get("platform") or "instagram"
        pillar = (brand or {}).get("pillar") or payload.get("content_pillar") or "Brand storytelling"
        references = list((research or {}).get("references") or [])
        base_titles = [
            "Teach your audience the biggest win they can expect",
            "Solve a friction point with a practical example",
            "Turn a customer story into a social proof moment",
            "Spotlight a behind-the-scenes decision that builds trust",
            "Address a common objection before it slows action",
            "Share a short expert framework your audience can reuse",
            "Compare your approach to a common industry mistake",
            "Invite a conversation around a simple question your audience is asking",
        ]
        ideas = []
        for title in base_titles[:8]:
            idea = {
                "title": f"{title} | {topic.title()}",
                "description": f"Create a {platform}-specific post exploring how {topic.lower()} supports {objective.lower()} while staying aligned with the brand's {pillar.lower()} strategy.",
                "content_angle": "Practical insight with a clear example and a conversational opener.",
                "target_audience": (brand or {}).get("audience") or "target audience",
                "recommended_platform": platform,
                "suggested_content_type": payload.get("content_type") or "educational",
                "objective": objective,
                "suggested_hook": f"Here’s the one mistake people make when {topic.lower()}...",
                "relevant_content_pillar": pillar,
                "supporting_references": references[:2],
            }
            ideas.append(idea)
        return ideas

    def generate(self, payload: dict[str, Any], *, brand: dict[str, Any] | None = None, research: dict[str, Any] | None = None) -> dict[str, Any]:
        prompt = PromptBuilder.build_ideation_prompt(payload, brand=brand, research=research)
        response = self._call_groq(prompt)
        ideas = response.get("ideas") if isinstance(response.get("ideas"), list) else None
        if not ideas:
            ideas = self._fallback_ideas(payload, brand=brand, research=research)

        normalized = []
        for idea in ideas[:10]:
            if not isinstance(idea, dict):
                continue
            normalized.append({
                "title": OutputValidator.normalize_string(idea.get("title"), "Content idea"),
                "description": OutputValidator.normalize_string(idea.get("description"), "No description provided."),
                "content_angle": OutputValidator.normalize_string(idea.get("content_angle"), "Use a practical angle."),
                "target_audience": OutputValidator.normalize_string(idea.get("target_audience"), (brand or {}).get("audience") or "target audience"),
                "recommended_platform": OutputValidator.normalize_string(idea.get("recommended_platform"), payload.get("platform") or "instagram"),
                "suggested_content_type": OutputValidator.normalize_string(idea.get("suggested_content_type"), payload.get("content_type") or "social content"),
                "objective": OutputValidator.normalize_string(idea.get("objective"), payload.get("objective") or "increase engagement"),
                "suggested_hook": OutputValidator.normalize_string(idea.get("suggested_hook"), "Start with a relevant problem or question."),
                "relevant_content_pillar": OutputValidator.normalize_string(idea.get("relevant_content_pillar"), (brand or {}).get("pillar") or "General brand messaging"),
                "supporting_references": OutputValidator.normalize_list(idea.get("supporting_references"))[:5],
            })
        return {"ideas": normalized, "count": len(normalized), "workspace_id": str(self.workspace_id)}
