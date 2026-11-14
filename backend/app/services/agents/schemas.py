"""Structured input and output schemas for the Phase 11 agents.

Agents talk to the orchestrator only through these models. Model output is
untrusted: it is parsed as JSON, validated here (unknown keys are dropped,
wrong types are rejected) and then checked again by each agent's ``finalize``
step against the records it was given (sources, metrics, brand rules).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Platform = Literal["facebook", "instagram"]
PLATFORMS: tuple[str, ...] = ("facebook", "instagram")

FACT_CLASSIFICATIONS = (
    "SUPPORTED",
    "PARTIALLY_SUPPORTED",
    "UNSUPPORTED",
    "CONTRADICTED",
    "OPINION",
    "UNVERIFIABLE",
)
FactClassification = Literal[
    "SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "OPINION", "UNVERIFIABLE"
]

SHORT = 400
MEDIUM = 1200
LONG = 4000


class AgentModel(BaseModel):
    """Base for agent payloads: unknown keys are ignored, strings are trimmed."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


def _clean_list(values: Any, *, limit: int, max_chars: int = SHORT) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        raise ValueError("Expected a list of strings.")
    cleaned: list[str] = []
    for item in values:
        if isinstance(item, (dict, list)):
            raise ValueError("Expected a list of strings.")
        text = " ".join(str(item).split())
        if text:
            cleaned.append(text[:max_chars])
    return cleaned[:limit]


class _Lists(AgentModel):
    """Mixin: every ``list[str]`` field is cleaned and capped."""

    @field_validator("*", mode="before")
    @classmethod
    def _normalize_string_lists(cls, value: Any, info):  # noqa: ANN001
        field = cls.model_fields.get(info.field_name)
        if field is not None and field.annotation == list[str]:
            return _clean_list(value, limit=12)
        return value


# Evidence -------------------------------------------------------------------------


class SourceRef(AgentModel):
    """A research source an agent may cite. ``ref`` is the short id used in prompts (S1, S2...)."""

    ref: str
    source_id: str
    research_id: str
    title: str
    url: str
    domain: str | None = None


# Inputs ---------------------------------------------------------------------------


class ResearchInput(AgentModel):
    task: str = Field(min_length=3, max_length=2000)
    brand_id: str | None = None
    research_ids: list[str] = Field(default_factory=list, max_length=5)
    run_new_research: bool = False


class StrategyInput(AgentModel):
    task: str = Field(min_length=3, max_length=2000)
    brand_id: str | None = None
    research_ids: list[str] = Field(default_factory=list, max_length=6)
    research_findings: dict[str, Any] | None = None
    analytics_insights: dict[str, Any] | None = None
    analytics_days: int | None = Field(default=None, ge=7, le=90)


class PlanInput(AgentModel):
    task: str = Field(min_length=3, max_length=2000)
    brand_id: str | None = None
    platforms: list[Platform] = Field(default_factory=lambda: ["facebook", "instagram"], min_length=1)
    strategy: dict[str, Any] | None = None
    research_findings: dict[str, Any] | None = None
    research_ids: list[str] = Field(default_factory=list, max_length=6)
    source_content: dict[str, Any] | None = None
    idea_count: int = Field(default=5, ge=1, le=8)


class WriterInput(AgentModel):
    task: str = Field(min_length=3, max_length=2000)
    brand_id: str | None = None
    platforms: list[Platform] = Field(default_factory=lambda: ["facebook", "instagram"], min_length=1)
    plan: dict[str, Any] | None = None
    research_ids: list[str] = Field(default_factory=list, max_length=6)
    source_content: dict[str, Any] | None = None
    previous_draft: dict[str, Any] | None = None
    revision_requests: list[str] = Field(default_factory=list, max_length=20)
    revision_round: int = Field(default=0, ge=0, le=10)


class BrandReviewInput(AgentModel):
    brand_id: str | None = None
    draft: dict[str, Any]


class FactCheckInput(AgentModel):
    draft: dict[str, Any]
    research_ids: list[str] = Field(default_factory=list, max_length=6)


class QualityInput(AgentModel):
    draft: dict[str, Any]
    task: str = Field(default="", max_length=2000)


class AnalyticsInput(AgentModel):
    task: str = Field(min_length=3, max_length=2000)
    brand_id: str | None = None
    days: int = Field(default=30, ge=7, le=90)


# Outputs --------------------------------------------------------------------------


class ResearchFindingOut(AgentModel):
    claim: str = Field(min_length=3, max_length=MEDIUM)
    explanation: str = Field(default="", max_length=MEDIUM)
    category: Literal["industry", "competitor", "audience", "trend", "opportunity", "other"] = "other"
    source_refs: list[str] = Field(default_factory=list, max_length=8)
    # Set by the agent's validation, never trusted from the model.
    verified: bool = False
    source_ids: list[str] = Field(default_factory=list)


class ResearchOutput(_Lists):
    summary: str = Field(min_length=3, max_length=LONG)
    findings: list[ResearchFindingOut] = Field(default_factory=list, max_length=15)
    audience_needs: list[str] = Field(default_factory=list)
    trends: list[str] = Field(default_factory=list)
    content_opportunities: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ContentMixItem(AgentModel):
    format: str = Field(min_length=2, max_length=80)
    share_percent: int = Field(ge=0, le=100)
    rationale: str = Field(default="", max_length=SHORT)


class EvidenceStatement(AgentModel):
    statement: str = Field(min_length=3, max_length=MEDIUM)
    source_refs: list[str] = Field(default_factory=list, max_length=8)
    basis: Literal["research", "analytics", "brand_profile", "assumption"] = "assumption"
    source_ids: list[str] = Field(default_factory=list)


class StrategyOutput(_Lists):
    strategy_summary: str = Field(min_length=3, max_length=LONG)
    audience_insights: list[str] = Field(default_factory=list)
    recommended_themes: list[str] = Field(min_length=1)
    content_pillars: list[str] = Field(default_factory=list)
    campaign_objectives: list[str] = Field(default_factory=list)
    content_mix: list[ContentMixItem] = Field(default_factory=list, max_length=8)
    supporting_evidence: list[EvidenceStatement] = Field(default_factory=list, max_length=12)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ContentIdea(AgentModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=3, max_length=MEDIUM)
    content_angle: str = Field(default="", max_length=SHORT)
    platform: Platform
    format: str = Field(default="text_post", max_length=40)
    content_pillar: str | None = Field(default=None, max_length=160)
    objective: str = Field(default="", max_length=SHORT)
    suggested_hook: str = Field(default="", max_length=SHORT)
    source_refs: list[str] = Field(default_factory=list, max_length=8)
    source_ids: list[str] = Field(default_factory=list)


class PublishingFrequency(AgentModel):
    posts_per_week: int = Field(ge=1, le=21)
    rationale: str = Field(default="", max_length=SHORT)


class PlatformAdaptation(AgentModel):
    platform: Platform
    guidance: str = Field(min_length=3, max_length=MEDIUM)


class PlanOutput(_Lists):
    ideas: list[ContentIdea] = Field(min_length=1, max_length=10)
    # A suggestion for people to consider. Nothing is scheduled by this agent.
    suggested_publishing_frequency: PublishingFrequency | None = None
    platform_adaptations: list[PlatformAdaptation] = Field(default_factory=list, max_length=4)
    notes: list[str] = Field(default_factory=list)


class DraftVersion(AgentModel):
    platform: Platform
    hook: str = Field(min_length=3, max_length=500)
    body: str = Field(min_length=10, max_length=5000)
    cta: str = Field(default="", max_length=400)
    hashtags: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("hashtags", mode="before")
    @classmethod
    def _hashtags(cls, value: Any) -> list[str]:
        tags: list[str] = []
        for item in _clean_list(value, limit=30, max_chars=80):
            tag = item.replace(" ", "")
            tags.append(tag if tag.startswith("#") else f"#{tag.lstrip('#')}")
        return tags


class WriterOutput(_Lists):
    title: str = Field(min_length=2, max_length=200)
    versions: list[DraftVersion] = Field(min_length=1, max_length=2)
    alternative_hooks: list[str] = Field(default_factory=list)
    cta_recommendations: list[str] = Field(default_factory=list)
    # Factual statements the draft makes, listed so the Fact-Checker can test them.
    factual_claims: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class BrandIssue(AgentModel):
    category: Literal["tone", "terminology", "prohibited_phrase", "unsupported_claim", "guideline"]
    severity: Literal["low", "medium", "high"]
    platform: Platform | None = None
    excerpt: str = Field(default="", max_length=SHORT)
    explanation: str = Field(min_length=3, max_length=MEDIUM)
    suggestion: str = Field(default="", max_length=MEDIUM)
    detected_by: Literal["rule", "model"] = "model"


class BrandReviewOutput(_Lists):
    assessment: Literal["consistent", "minor_issues", "major_issues"]
    summary: str = Field(min_length=3, max_length=LONG)
    issues: list[BrandIssue] = Field(default_factory=list, max_length=20)
    suggested_improvements: list[str] = Field(default_factory=list)


class ClaimAssessment(AgentModel):
    claim: str = Field(min_length=3, max_length=MEDIUM)
    classification: FactClassification
    reasoning: str = Field(default="", max_length=MEDIUM)
    source_refs: list[str] = Field(default_factory=list, max_length=8)
    source_ids: list[str] = Field(default_factory=list)


class FactCheckOutput(AgentModel):
    claims: list[ClaimAssessment] = Field(default_factory=list, max_length=25)
    summary: str = Field(min_length=3, max_length=LONG)


class ScoreItem(AgentModel):
    score: int = Field(ge=1, le=10)
    explanation: str = Field(min_length=3, max_length=MEDIUM)


class QualityScores(AgentModel):
    clarity: ScoreItem
    readability: ScoreItem
    structure: ScoreItem
    hook_strength: ScoreItem
    cta_quality: ScoreItem
    platform_suitability: ScoreItem


class QualityOutput(_Lists):
    scores: QualityScores
    repetition_issues: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=3, max_length=LONG)


class MetricRef(AgentModel):
    metric: str = Field(min_length=2, max_length=80)
    value: float
    scope: str = Field(default="", max_length=200)


class AnalyticsPattern(AgentModel):
    observation: str = Field(min_length=3, max_length=MEDIUM)
    metric_refs: list[MetricRef] = Field(default_factory=list, max_length=6)


class AnalyticsRecommendation(AgentModel):
    recommendation: str = Field(min_length=3, max_length=MEDIUM)
    rationale: str = Field(default="", max_length=MEDIUM)


class AnalyticsExperiment(AgentModel):
    hypothesis: str = Field(min_length=3, max_length=MEDIUM)
    change: str = Field(default="", max_length=MEDIUM)
    measure: str = Field(default="", max_length=SHORT)


class AnalyticsOutput(_Lists):
    performance_summary: str = Field(min_length=3, max_length=LONG)
    patterns: list[AnalyticsPattern] = Field(default_factory=list, max_length=10)
    opportunities: list[str] = Field(default_factory=list)
    recommendations: list[AnalyticsRecommendation] = Field(default_factory=list, max_length=10)
    experiments: list[AnalyticsExperiment] = Field(default_factory=list, max_length=6)
    data_limitations: list[str] = Field(default_factory=list)


# Response envelope ----------------------------------------------------------------


class TokenUsage(AgentModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class AgentResponse(AgentModel):
    """What every step stores in ``agent_executions.output_data``."""

    agent_id: str
    agent_version: str
    task_id: str
    execution_id: str
    status: Literal["succeeded", "failed", "cancelled"]
    result: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    duration_ms: int = 0
    model: str | None = None
