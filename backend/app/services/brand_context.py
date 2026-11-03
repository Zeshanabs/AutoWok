from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session as DBSession, joinedload, selectinload

from app.api.v1.dependencies.auth import authorize_workspace
from app.models import Brand, User
from app.schemas.brands import BrandContext


class BrandContextService:
    schema_version = "1"

    def get_brand_context(
        self,
        brand_id: UUID,
        workspace_id: UUID,
        current_user: User,
        db: DBSession,
    ) -> BrandContext:
        authorize_workspace(workspace_id, current_user, db)
        brand = (
            db.query(Brand)
            .options(
                joinedload(Brand.voice),
                selectinload(Brand.audiences),
                selectinload(Brand.pillars),
                selectinload(Brand.goals),
                selectinload(Brand.policies),
            )
            .filter(
                Brand.id == brand_id,
                Brand.workspace_id == workspace_id,
                Brand.status == "ACTIVE",
            )
            .first()
        )
        if brand is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Brand not found."
            )

        voice = brand.voice
        active_policies = [policy for policy in brand.policies if policy.is_active]
        restrictions = [
            {
                "type": policy.policy_type,
                "name": policy.name,
                "value": policy.policy_value,
                "severity": policy.severity,
            }
            for policy in active_policies
        ]
        voice_data = None
        languages: list[str] = []
        if voice is not None:
            languages = list(voice.language_preferences or [])
            voice_data = {
                "tone": voice.tone,
                "personality": voice.personality,
                "writing_style": voice.writing_style,
                "communication_style": voice.communication_style,
                "vocabulary_preferences": voice.vocabulary_preferences or [],
                "preferred_phrases": voice.preferred_phrases or [],
                "prohibited_phrases": voice.prohibited_phrases or [],
                "language_preferences": languages,
                "emoji_policy": voice.emoji_policy,
                "hashtag_policy": voice.hashtag_policy,
                "call_to_action_style": voice.call_to_action_style,
            }

        return BrandContext(
            context_version=self.schema_version,
            brand={
                "id": str(brand.id),
                "workspace_id": str(brand.workspace_id),
                "name": brand.name,
                "slug": brand.slug,
                "description": brand.description,
                "website_url": brand.website_url,
                "logo_url": brand.logo_url,
                "industry": brand.industry,
                "business_type": brand.business_type,
                "primary_color": brand.primary_color,
                "secondary_color": brand.secondary_color,
            },
            voice=voice_data,
            audiences=[
                {
                    "name": audience.audience_name,
                    "description": audience.description,
                    "age_range": audience.age_range,
                    "locations": audience.locations or [],
                    "interests": audience.interests or [],
                    "pain_points": audience.pain_points or [],
                    "goals": audience.goals or [],
                    "preferred_platforms": audience.preferred_platforms or [],
                    "demographics": audience.demographics,
                }
                for audience in brand.audiences
            ],
            content_pillars=[
                {
                    "name": pillar.name,
                    "description": pillar.description,
                    "objective": pillar.objective,
                    "suggested_topics": pillar.suggested_topics or [],
                    "priority": pillar.priority,
                }
                for pillar in brand.pillars
                if pillar.is_active
            ],
            goals=[
                {
                    "type": goal.goal_type,
                    "title": goal.title,
                    "description": goal.description,
                    "priority": goal.priority,
                    "target_metric": goal.target_metric,
                    "target_value": goal.target_value,
                    "target_period": goal.target_period,
                }
                for goal in brand.goals
                if goal.is_active
            ],
            policies=restrictions,
            language_preferences=languages,
            communication_restrictions=[
                policy["value"] for policy in restrictions
            ]
            + (voice.prohibited_phrases or [] if voice else []),
        )


brand_context_service = BrandContextService()
