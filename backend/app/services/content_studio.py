from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from app.models import Brand, ContentDraft, ContentProject, ContentVersion, ResearchReport
from app.models.brand import BrandVoice, ContentPillar, TargetAudience
from app.services.groq import GroqService


class ContentValidationError(ValueError):
    pass


@dataclass
class GeneratedDraft:
    title: str
    hook: str
    body: str
    cta: str
    hashtags: list[str]
    platform: str
    variations: list[str]

    def as_payload(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "hook": self.hook,
            "body": self.body,
            "cta": self.cta,
            "hashtags": self.hashtags,
            "platform": self.platform,
            "variations": self.variations,
        }


class ContentStudioService:
    def __init__(self, db: DBSession) -> None:
        self.db = db

    def build_brand_context(self, project: ContentProject) -> dict[str, Any]:
        brand = self.db.query(Brand).filter(Brand.id == project.brand_id).first() if project.brand_id else None
        voice = self.db.query(BrandVoice).filter(BrandVoice.brand_id == project.brand_id).first() if project.brand_id else None
        audience = (
            self.db.query(TargetAudience)
            .filter(TargetAudience.brand_id == project.brand_id)
            .order_by(TargetAudience.created_at.desc())
            .first()
            if project.brand_id
            else None
        )
        pillar = (
            self.db.query(ContentPillar)
            .filter(ContentPillar.brand_id == project.brand_id, ContentPillar.is_active.is_(True))
            .order_by(ContentPillar.priority.asc(), ContentPillar.created_at.desc())
            .first()
            if project.brand_id
            else None
        )
        report = (
            self.db.query(ResearchReport)
            .filter(ResearchReport.id == project.research_report_id)
            .first()
            if project.research_report_id
            else None
        )
        return {
            "brand": {
                "name": brand.name if brand else "your brand",
                "description": brand.description if brand else None,
                "industry": brand.industry if brand else None,
            },
            "voice": {
                "tone": voice.tone if voice else project.preferred_tone,
                "personality": voice.personality if voice else None,
                "writing_style": voice.writing_style if voice else None,
                "preferred_phrases": voice.preferred_phrases if voice else [],
                "prohibited_phrases": voice.prohibited_phrases if voice else [],
                "emoji_policy": voice.emoji_policy if voice else None,
                "hashtag_policy": voice.hashtag_policy if voice else None,
                "cta_style": voice.call_to_action_style if voice else None,
            },
            "audience": {
                "name": audience.audience_name if audience else project.target_audience,
                "description": audience.description if audience else None,
                "interests": audience.interests if audience else [],
                "pain_points": audience.pain_points if audience else [],
                "goals": audience.goals if audience else [],
            },
            "pillar": {
                "name": pillar.name if pillar else project.content_pillar,
                "description": pillar.description if pillar else None,
                "objective": pillar.objective if pillar else None,
            },
            "research": {
                "summary": report.executive_summary if report else None,
                "findings": report.key_findings if report else [],
                "trends": report.trends if report else [],
            },
        }

    def validate_platform(self, platform: str, draft: dict[str, Any]) -> list[str]:
        return self.platform_validation(platform, draft)["errors"]

    def platform_validation(self, platform: str, draft: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        caption = "\n\n".join(
            str(part).strip()
            for part in (draft.get("hook"), draft.get("body"), draft.get("cta"))
            if part and str(part).strip()
        )
        hashtags = [str(tag).strip() for tag in (draft.get("hashtags") or []) if str(tag).strip()]
        if platform == "instagram":
            if len(caption) > 2200:
                errors.append("Instagram captions should stay under 2,200 characters.")
            if len(hashtags) > 30:
                errors.append("Instagram posts should use at most 30 hashtags.")
        elif platform == "facebook":
            if len(caption) > 63206:
                errors.append("Facebook captions should stay under 63,206 characters.")
            if len(hashtags) > 10:
                warnings.append("Facebook posts generally work best with 10 or fewer hashtags.")
        else:
            errors.append("The selected platform is not supported.")

        if not caption:
            errors.append("A caption, hook, or body is required for the selected platform.")
        if any(not tag.startswith("#") for tag in hashtags):
            errors.append("Every hashtag must start with '#'.")
        return {
            "platform": platform,
            "valid": not errors,
            "caption_length": len(caption),
            "hashtag_count": len(hashtags),
            "errors": errors,
            "warnings": warnings,
        }

    def _parse_generated_output(self, raw_text: str, platform: str) -> GeneratedDraft:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```\s*$", "", cleaned)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            payload = {
                "title": "Content idea",
                "hook": cleaned[:220],
                "body": cleaned,
                "cta": "Learn more today.",
                "hashtags": ["#content", f"#{platform}"],
                "variations": [cleaned[:500]],
            }
        if not isinstance(payload, dict):
            payload = {
                "title": "Content idea",
                "hook": str(cleaned[:220]),
                "body": str(cleaned),
                "cta": "Learn more today.",
                "hashtags": ["#content", f"#{platform}"],
                "variations": [str(cleaned[:500])],
            }
        title = str(payload.get("title") or "Content idea")
        hook = str(payload.get("hook") or payload.get("opening") or "Need a stronger opening hook.")
        body = str(payload.get("body") or payload.get("caption") or payload.get("content") or "")
        cta = str(payload.get("cta") or payload.get("call_to_action") or "Learn more today.")
        hashtags = payload.get("hashtags") or []
        if not isinstance(hashtags, list):
            hashtags = [str(hashtags)] if hashtags else []
        hashtags = [str(item).strip() for item in hashtags if str(item).strip()]
        variations = payload.get("variations") or []
        if not isinstance(variations, list):
            variations = [str(variations)] if variations else []
        return GeneratedDraft(
            title=title,
            hook=hook,
            body=body,
            cta=cta,
            hashtags=hashtags,
            platform=platform,
            variations=[str(item).strip() for item in variations if str(item).strip()],
        )

    def generate_for_project(self, project: ContentProject, *, platform: str | None = None) -> GeneratedDraft:
        target_platform = platform or (project.selected_platforms[0] if project.selected_platforms else "instagram")
        context = self.build_brand_context(project)
        report_text = ""
        if context["research"]["summary"]:
            report_text = "\n".join(
                [
                    "Research summary:",
                    str(context["research"]["summary"]),
                    "Key findings:",
                    "\n".join(str(item) for item in context["research"]["findings"][:5]),
                ]
            )
        prompt = f"""
You are an expert social media strategist and copywriter.
Create a platform-ready draft tailored to {context['brand']['name']}.
Brand identity: {context['brand']['description'] or 'N/A'}
Tone: {context['voice']['tone'] or project.preferred_tone or 'confident'}
Audience: {context['audience']['name'] or project.target_audience or 'target customers'}
Content pillar: {context['pillar']['name'] or project.content_pillar or 'general'}
Objective: {project.objective or project.topic or 'drive engagement and awareness'}
Content type: {project.content_type}
Language: {project.language}
Platform: {target_platform}
Required phrases: {', '.join(project.required_phrases) if project.required_phrases else 'none'}
Prohibited phrases: {', '.join(project.prohibited_phrases) if project.prohibited_phrases else 'none'}
CTA requirements: {project.cta_requirements or 'Use a natural CTA aligned to the brand.'}
Hashtag preferences: {project.hashtag_preferences or 'Keep it platform-appropriate and concise.'}
Emoji preferences: {project.emoji_preferences or 'Use sparingly if relevant.'}
Research context:
{report_text or 'No research report attached.'}
Return valid JSON only with keys: title, hook, body, cta, hashtags, variations.
Rules:
- Keep the answer concise but actionable.
- The hashtags array must be strings that start with '#'.
- Ensure the hook is attention-grabbing and the CTA is clear.
- Do not include markdown fences or commentary outside JSON.
""".strip()
        service = GroqService(self.db, project.workspace_id)
        completion = service.generate_completion(prompt, max_tokens=1200, temperature=0.7)
        generated = self._parse_generated_output(completion.text, target_platform)
        if not generated.title.strip() or not generated.body.strip() or not generated.hook.strip():
            raise ContentValidationError("The generated content is incomplete. Please try again with a more specific brief.")
        errors = self.validate_platform(target_platform, generated.as_payload())
        if errors:
            raise ContentValidationError("; ".join(errors))
        return generated

    def create_draft(self, project: ContentProject, *, platform: str) -> ContentDraft:
        draft = ContentDraft(
            project_id=project.id,
            platform=platform,
            title="",
            hook="",
            body="",
            cta="",
            hashtags=[],
            status="draft",
            ai_generated=False,
        )
        self.db.add(draft)
        self.db.flush()
        return draft

    def create_version(self, draft: ContentDraft, *, change_reason: str, created_by: UUID | None = None) -> ContentVersion:
        version = ContentVersion(
            draft_id=draft.id,
            version_number=(draft.version_count or 0) + 1,
            platform=draft.platform,
            title=draft.title,
            hook=draft.hook,
            body=draft.body,
            cta=draft.cta,
            hashtags=list(draft.hashtags or []),
            snapshot={
                "title": draft.title,
                "hook": draft.hook,
                "body": draft.body,
                "cta": draft.cta,
                "hashtags": list(draft.hashtags or []),
                "platform": draft.platform,
            },
            change_reason=change_reason,
            created_by=created_by,
        )
        self.db.add(version)
        draft.version_count = version.version_number
        self.db.flush()
        return version
