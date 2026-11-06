from __future__ import annotations

from typing import Any


def build_content_prompt(project: Any, context: dict[str, Any], platform: str) -> str:
    brand = context.get("brand", {})
    voice = context.get("voice", {})
    audience = context.get("audience", {})
    pillar = context.get("pillar", {})
    research = context.get("research", {})
    research_summary = research.get("summary") or "No research report attached."
    research_findings = research.get("findings") or []
    findings_text = "\n".join(str(item) for item in research_findings[:5])
    return f"""
You are an expert social media strategist and copywriter.
Create a platform-ready draft tailored to {brand.get('name', 'your brand')}.
Brand identity: {brand.get('description') or 'N/A'}
Tone: {voice.get('tone') or getattr(project, 'preferred_tone', None) or 'confident'}
Audience: {audience.get('name') or getattr(project, 'target_audience', None) or 'target customers'}
Content pillar: {pillar.get('name') or getattr(project, 'content_pillar', None) or 'general'}
Objective: {getattr(project, 'objective', None) or getattr(project, 'topic', None) or 'drive engagement and awareness'}
Content type: {getattr(project, 'content_type', 'text_post')}
Language: {getattr(project, 'language', 'en')}
Platform: {platform}
Required phrases: {', '.join(getattr(project, 'required_phrases', []) or []) if getattr(project, 'required_phrases', None) else 'none'}
Prohibited phrases: {', '.join(getattr(project, 'prohibited_phrases', []) or []) if getattr(project, 'prohibited_phrases', None) else 'none'}
CTA requirements: {getattr(project, 'cta_requirements', None) or 'Use a natural CTA aligned to the brand.'}
Hashtag preferences: {getattr(project, 'hashtag_preferences', None) or 'Keep it platform-appropriate and concise.'}
Emoji preferences: {getattr(project, 'emoji_preferences', None) or 'Use sparingly if relevant.'}
Research context:
{research_summary}
Key findings:
{findings_text or 'No findings attached.'}
Return valid JSON only with keys: title, hook, body, cta, hashtags, variations.
Keep the answer concise but actionable; the hashtags array should be strings that start with '#'.
""".strip()
