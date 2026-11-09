from __future__ import annotations

from typing import Any


class PromptBuilder:
    """Build domain-specific prompts for autonomous content intelligence tasks."""

    @staticmethod
    def _stringify(value: Any, default: str = "Not provided") -> str:
        if value is None:
            return default
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(item) for item in value if str(item).strip()) or default
        return str(value)

    @classmethod
    def brand_context(cls, brand: dict[str, Any] | None, *, fallback_name: str = "your brand") -> dict[str, Any]:
        brand = brand or {}
        return {
            "name": cls._stringify(brand.get("name"), fallback_name),
            "industry": cls._stringify(brand.get("industry"), "Not specified"),
            "description": cls._stringify(brand.get("description"), "No brand description provided."),
            "voice": cls._stringify(brand.get("voice"), "Not specified"),
            "audience": cls._stringify(brand.get("audience"), "Not specified"),
            "pillar": cls._stringify(brand.get("pillar"), "Not specified"),
            "policies": brand.get("policies") or [],
        }

    @classmethod
    def research_context(cls, report: dict[str, Any] | None, *, fallback: str = "No research report was provided.") -> dict[str, Any]:
        report = report or {}
        return {
            "summary": cls._stringify(report.get("summary"), fallback),
            "findings": list(report.get("findings") or []),
            "trends": list(report.get("trends") or []),
            "references": list(report.get("references") or []),
        }

    @classmethod
    def build_ideation_prompt(cls, payload: dict[str, Any], brand: dict[str, Any] | None = None, research: dict[str, Any] | None = None) -> str:
        brand_ctx = cls.brand_context(brand)
        research_ctx = cls.research_context(research)
        return """
You are an expert social media strategist and brand content planner.
Generate content ideas that fit the brand and never invent facts, statistics, or unsupported claims.

Brand context:
- Brand: {brand_name}
- Industry: {industry}
- Description: {brand_description}
- Voice: {brand_voice}
- Audience: {brand_audience}
- Content pillar: {brand_pillar}

Research context:
- Summary: {research_summary}
- Key findings: {research_findings}
- Trends: {research_trends}
- References: {research_refs}

Input requirements:
- Topic or keyword: {topic}
- Campaign objective: {objective}
- Platform: {platform}
- Language: {language}
- Content type: {content_type}

Return valid JSON only with this schema:
{
  "ideas": [
    {
      "title": "string",
      "description": "string",
      "content_angle": "string",
      "target_audience": "string",
      "recommended_platform": "string",
      "suggested_content_type": "string",
      "objective": "string",
      "suggested_hook": "string",
      "relevant_content_pillar": "string",
      "supporting_references": ["string"]
    }
  ]
}

Requirements:
- Produce 6 to 10 ideas.
- Keep ideas grounded in the provided research context.
- Include only ideas supported by evidence when research exists.
- Do not claim a trend is current unless the research report supports it.
- Use concise but useful prose.
""".format(
            brand_name=brand_ctx["name"],
            industry=brand_ctx["industry"],
            brand_description=brand_ctx["description"],
            brand_voice=brand_ctx["voice"],
            brand_audience=brand_ctx["audience"],
            brand_pillar=brand_ctx["pillar"],
            research_summary=research_ctx["summary"],
            research_findings="; ".join(str(item) for item in research_ctx["findings"]) or "No specific findings were provided.",
            research_trends="; ".join(str(item) for item in research_ctx["trends"]) or "No trends were provided.",
            research_refs="; ".join(str(item) for item in research_ctx["references"]) or "No references were provided.",
            topic=cls._stringify(payload.get("topic"), "general brand growth"),
            objective=cls._stringify(payload.get("objective"), "increase engagement and brand awareness"),
            platform=cls._stringify(payload.get("platform"), "instagram"),
            language=cls._stringify(payload.get("language"), "en"),
            content_type=cls._stringify(payload.get("content_type"), "social content"),
        )

    @classmethod
    def build_writing_prompt(cls, payload: dict[str, Any], brand: dict[str, Any] | None = None) -> str:
        return """
You are a senior copywriter. Improve the provided draft without inventing facts.
Brand context:
- Brand: {brand_name}
- Voice: {brand_voice}
- Audience: {brand_audience}
- Policy notes: {policies}

Task:
- Action: {action}
- Platform: {platform}
- Tone: {tone}
- Objective: {objective}

Source text:
{text}

Return valid JSON only with this schema:
{
  "output": "string",
  "hook": "string",
  "cta": "string",
  "hashtags": ["string"],
  "notes": ["string"],
  "readability_score": 0,
  "brand_alignment": "string"
}
""".format(
            brand_name=cls._stringify((brand or {}).get("name"), "your brand"),
            brand_voice=cls._stringify((brand or {}).get("voice"), "Use the brand's configured voice first."),
            brand_audience=cls._stringify((brand or {}).get("audience"), "general audience"),
            policies="; ".join(str(item) for item in ((brand or {}).get("policies") or [])) or "No explicit brand policy restrictions.",
            action=cls._stringify(payload.get("action"), "improve writing"),
            platform=cls._stringify(payload.get("platform"), "instagram"),
            tone=cls._stringify(payload.get("tone"), "Professional"),
            objective=cls._stringify(payload.get("objective"), "drive engagement"),
            text=payload.get("text") or "",
        )

    @classmethod
    def build_critique_prompt(cls, payload: dict[str, Any], brand: dict[str, Any] | None = None) -> str:
        return """
Assess the quality of this content for a social brand.
Return valid JSON only.

Brand context:
- Brand: {brand_name}
- Voice: {brand_voice}
- Audience: {brand_audience}

Content:
{text}

Return schema:
{
  "score": 0,
  "summary": "string",
  "strengths": ["string"],
  "improvements": ["string"],
  "brand_voice": "string",
  "readability": "string",
  "cta_strength": "string",
  "risk_flags": ["string"]
}
""".format(
            brand_name=cls._stringify((brand or {}).get("name"), "your brand"),
            brand_voice=cls._stringify((brand or {}).get("voice"), "Professional and clear"),
            brand_audience=cls._stringify((brand or {}).get("audience"), "general audience"),
            text=payload.get("text") or "",
        )

    @classmethod
    def build_fact_check_prompt(cls, payload: dict[str, Any], research: dict[str, Any] | None = None) -> str:
        return """
Review the content claims and compare them with the research evidence.
You must not fabricate evidence.
Return valid JSON only.

Claim list:
{claims}

Research context:
{research_summary}

Evidence sources:
{references}

Return schema:
{
  "claims": [
    {
      "claim": "string",
      "status": "supported|unsupported|unclear",
      "reasoning": "string",
      "evidence": ["string"]
    }
  ],
  "overall_verdict": "string"
}
""".format(
            claims="\n".join(f"- {item}" for item in (payload.get("claims") or [])) or "No specific claims were provided.",
            research_summary=(research or {}).get("summary") or "No research report was provided.",
            references="\n".join(str(item) for item in ((research or {}).get("references") or [])) or "No references were provided.",
        )
