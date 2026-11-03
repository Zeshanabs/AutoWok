from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import re
from typing import Any
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    field_validator,
    model_validator,
)


class APIModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        use_enum_values=True,
        extra="forbid",
        protected_namespaces=(),
    )


class BrandStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class GoalType(StrEnum):
    BRAND_AWARENESS = "brand_awareness"
    ENGAGEMENT = "engagement"
    LEAD_GENERATION = "lead_generation"
    WEBSITE_TRAFFIC = "website_traffic"
    COMMUNITY_BUILDING = "community_building"
    CUSTOMER_EDUCATION = "customer_education"
    CUSTOM = "custom"


class PolicyType(StrEnum):
    PROHIBITED_CLAIM = "prohibited_claim"
    RESTRICTED_TOPIC = "restricted_topic"
    REQUIRED_DISCLAIMER = "required_disclaimer"
    COMPETITOR_REFERENCE = "competitor_reference"
    INDUSTRY_RULE = "industry_rule"
    LEGAL_COMPLIANCE = "legal_compliance"
    APPROVAL_REQUIRED = "approval_required"
    CUSTOM = "custom"


class PolicySeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ProviderName(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OPENAI_COMPATIBLE = "openai_compatible"


class BrandCreate(APIModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str | None = Field(default=None, min_length=2, max_length=140, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = Field(default=None, max_length=5000)
    website_url: AnyHttpUrl | None = None
    industry: str | None = Field(default=None, max_length=120)
    business_type: str | None = Field(default=None, max_length=120)
    logo_url: AnyHttpUrl | None = None
    primary_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Brand name must contain at least two characters.")
        return value


class BrandUpdate(APIModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    slug: str | None = Field(default=None, min_length=2, max_length=140, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = Field(default=None, max_length=5000)
    website_url: AnyHttpUrl | None = None
    industry: str | None = Field(default=None, max_length=120)
    business_type: str | None = Field(default=None, max_length=120)
    logo_url: AnyHttpUrl | None = None
    primary_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Brand name must contain at least two characters.")
        return value


class BrandRead(APIModel):
    id: UUID
    workspace_id: UUID
    name: str
    slug: str
    description: str | None
    website_url: str | None
    industry: str | None
    business_type: str | None
    logo_url: str | None
    primary_color: str | None
    secondary_color: str | None
    status: BrandStatus
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class BrandVoiceInput(APIModel):
    tone: str | None = Field(default=None, max_length=120)
    personality: str | None = Field(default=None, max_length=3000)
    writing_style: str | None = Field(default=None, max_length=3000)
    communication_style: str | None = Field(default=None, max_length=3000)
    vocabulary_preferences: list[str] = Field(default_factory=list, max_length=50)
    preferred_phrases: list[str] = Field(default_factory=list, max_length=50)
    prohibited_phrases: list[str] = Field(default_factory=list, max_length=50)
    language_preferences: list[str] = Field(default_factory=list, max_length=20)
    emoji_policy: str | None = Field(default=None, pattern=r"^(avoid|sparingly|contextual|frequent)$")
    hashtag_policy: str | None = Field(default=None, pattern=r"^(avoid|limited|moderate|platform_specific)$")
    call_to_action_style: str | None = Field(default=None, max_length=120)

    @field_validator(
        "vocabulary_preferences",
        "preferred_phrases",
        "prohibited_phrases",
        "language_preferences",
    )
    @classmethod
    def validate_phrases(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 200 for value in cleaned):
            raise ValueError("Each item must contain 1 to 200 characters.")
        return cleaned


class BrandVoiceRead(BrandVoiceInput):
    id: UUID
    brand_id: UUID
    created_at: datetime
    updated_at: datetime


class TargetAudienceInput(APIModel):
    audience_name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=3000)
    age_range: str | None = Field(default=None, max_length=40)
    locations: list[str] = Field(default_factory=list, max_length=50)
    interests: list[str] = Field(default_factory=list, max_length=50)
    pain_points: list[str] = Field(default_factory=list, max_length=50)
    goals: list[str] = Field(default_factory=list, max_length=50)
    preferred_platforms: list[str] = Field(default_factory=list, max_length=20)
    demographics: dict[str, JsonValue] | None = None

    @field_validator("audience_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Audience name must contain at least two characters.")
        return value

    @field_validator("locations", "interests", "pain_points", "goals", "preferred_platforms")
    @classmethod
    def clean_lists(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 200 for value in cleaned):
            raise ValueError("Each item must contain 1 to 200 characters.")
        return cleaned

    @field_validator("demographics")
    @classmethod
    def restrict_demographics(cls, value: dict[str, JsonValue] | None):
        forbidden = {"name", "email", "phone", "address", "ssn", "social_security"}

        def contains_pii_key(item: JsonValue) -> bool:
            if isinstance(item, dict):
                return any(
                    key.casefold() in forbidden or contains_pii_key(nested)
                    for key, nested in item.items()
                )
            if isinstance(item, list):
                return any(contains_pii_key(nested) for nested in item)
            return False

        if value and contains_pii_key(value):
            raise ValueError("Do not include personally identifying information.")
        return value


class TargetAudienceUpdate(APIModel):
    audience_name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=3000)
    age_range: str | None = Field(default=None, max_length=40)
    locations: list[str] | None = Field(default=None, max_length=50)
    interests: list[str] | None = Field(default=None, max_length=50)
    pain_points: list[str] | None = Field(default=None, max_length=50)
    goals: list[str] | None = Field(default=None, max_length=50)
    preferred_platforms: list[str] | None = Field(default=None, max_length=20)
    demographics: dict[str, JsonValue] | None = None

    @field_validator("audience_name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Audience name must contain at least two characters.")
        return value

    @field_validator("locations", "interests", "pain_points", "goals", "preferred_platforms")
    @classmethod
    def clean_lists(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 200 for value in cleaned):
            raise ValueError("Each item must contain 1 to 200 characters.")
        return cleaned

    @field_validator("demographics")
    @classmethod
    def restrict_demographics(cls, value: dict[str, JsonValue] | None):
        return TargetAudienceInput.restrict_demographics(value)


class TargetAudienceRead(TargetAudienceInput):
    id: UUID
    brand_id: UUID
    created_at: datetime
    updated_at: datetime


class ContentPillarInput(APIModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=3000)
    objective: str | None = Field(default=None, max_length=2000)
    suggested_topics: list[str] = Field(default_factory=list, max_length=50)
    priority: int = Field(default=3, ge=1, le=5)
    is_active: bool = True


class ContentPillarUpdate(APIModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=3000)
    objective: str | None = Field(default=None, max_length=2000)
    suggested_topics: list[str] | None = Field(default=None, max_length=50)
    priority: int | None = Field(default=None, ge=1, le=5)
    is_active: bool | None = None


class ContentPillarRead(ContentPillarInput):
    id: UUID
    brand_id: UUID
    created_at: datetime
    updated_at: datetime


class BrandGoalInput(APIModel):
    goal_type: GoalType
    title: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=3000)
    priority: int = Field(default=3, ge=1, le=5)
    target_metric: str | None = Field(default=None, max_length=120)
    target_value: str | None = Field(default=None, max_length=120)
    target_period: str | None = Field(default=None, max_length=80)
    is_active: bool = True


class BrandGoalUpdate(APIModel):
    goal_type: GoalType | None = None
    title: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=3000)
    priority: int | None = Field(default=None, ge=1, le=5)
    target_metric: str | None = Field(default=None, max_length=120)
    target_value: str | None = Field(default=None, max_length=120)
    target_period: str | None = Field(default=None, max_length=80)
    is_active: bool | None = None


class BrandGoalRead(BrandGoalInput):
    id: UUID
    brand_id: UUID
    created_at: datetime
    updated_at: datetime


class BrandPolicyInput(APIModel):
    policy_type: PolicyType
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=3000)
    policy_value: str = Field(min_length=1, max_length=5000)
    severity: PolicySeverity = PolicySeverity.MEDIUM
    is_active: bool = True


class BrandPolicyUpdate(APIModel):
    policy_type: PolicyType | None = None
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=3000)
    policy_value: str | None = Field(default=None, min_length=1, max_length=5000)
    severity: PolicySeverity | None = None
    is_active: bool | None = None


class BrandPolicyRead(BrandPolicyInput):
    id: UUID
    brand_id: UUID
    created_at: datetime
    updated_at: datetime


class BrandOverview(APIModel):
    brand: BrandRead
    voice: BrandVoiceRead | None
    audiences: list[TargetAudienceRead]
    pillars: list[ContentPillarRead]
    goals: list[BrandGoalRead]
    policies: list[BrandPolicyRead]


class BrandContext(APIModel):
    context_version: str = "1"
    brand: dict[str, Any]
    voice: dict[str, Any] | None
    audiences: list[dict[str, Any]]
    content_pillars: list[dict[str, Any]]
    goals: list[dict[str, Any]]
    policies: list[dict[str, Any]]
    language_preferences: list[str]
    communication_restrictions: list[str]


class AIProviderCreate(APIModel):
    provider_name: ProviderName
    display_name: str = Field(min_length=2, max_length=120)
    model_name: str = Field(min_length=1, max_length=160)
    api_key: SecretStr = Field(min_length=1, max_length=4096)
    base_url: AnyHttpUrl | None = None
    is_active: bool = True
    is_default: bool = False
    configuration: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("api_key")
    @classmethod
    def reject_empty_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Enter a non-empty API key.")
        return value

    @model_validator(mode="after")
    def validate_default(self):
        if self.is_default and not self.is_active:
            raise ValueError("An inactive provider cannot be the default.")
        _validate_safe_configuration(self.configuration)
        return self


class AIProviderUpdate(APIModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    model_name: str | None = Field(default=None, min_length=1, max_length=160)
    api_key: SecretStr | None = Field(default=None, max_length=4096)
    base_url: AnyHttpUrl | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    configuration: dict[str, JsonValue] | None = None

    @field_validator("api_key")
    @classmethod
    def reject_empty_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("Enter a non-empty replacement API key.")
        return value

    @field_validator("configuration")
    @classmethod
    def validate_config(cls, value: dict[str, JsonValue] | None):
        if value is not None:
            _validate_safe_configuration(value)
        return value


def _validate_safe_configuration(configuration: dict[str, JsonValue]) -> None:
    if len(str(configuration).encode("utf-8")) > 4096:
        raise ValueError("Provider configuration must be at most 4 KB.")
    forbidden = {
        "apikey",
        "secret",
        "token",
        "password",
        "authorization",
        "clientsecret",
        "accesstoken",
        "refreshtoken",
        "privatekey",
        "credential",
    }

    def walk(value: JsonValue) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
                if normalized_key in forbidden:
                    raise ValueError("Secrets must be provided only in the API key field.")
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(configuration)


class AIProviderRead(APIModel):
    id: UUID
    workspace_id: UUID
    provider_name: ProviderName
    display_name: str
    model_name: str
    base_url: str | None
    api_key_configured: bool
    masked_api_key: str
    is_active: bool
    is_default: bool
    configuration: dict[str, JsonValue]
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    last_tested_at: datetime | None
    last_test_status: str | None


class AIProviderTestResponse(APIModel):
    status: str
    message: str
    tested_at: datetime
