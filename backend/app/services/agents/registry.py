"""Agent registry: the only place agents come from.

Agents are Python objects registered at import time. Users cannot submit agent
code, prompts or tool lists; a workspace can only switch a registered agent on
or off (``agent_settings``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.models import AgentSetting
from app.services.agents.tools import TOOLS, AgentContext, ToolBox, describe_tools

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
ROLES = ("MEMBER", "ADMIN", "OWNER")
ROLE_RANK = {"MEMBER": 1, "ADMIN": 2, "OWNER": 3}
ORCHESTRATOR_KEY = "orchestrator"


class AgentRegistryError(Exception):
    pass


class UnknownAgentError(AgentRegistryError):
    pass


class AgentDisabledError(AgentRegistryError):
    pass


class InvalidAgentConfigError(AgentRegistryError):
    pass


@dataclass(frozen=True)
class ModelConfig:
    temperature: float = 0.4
    max_tokens: int = 1500


@dataclass(frozen=True)
class ExecutionLimits:
    """``None`` means "use the server setting"."""

    timeout_seconds: int | None = None
    max_attempts: int | None = None


@dataclass
class Prepared:
    """Result of an agent's ``prepare``: the prompt plus what ``finalize`` needs to check the answer."""

    prompt: str | None
    context: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # Set instead of ``prompt`` when no model call is needed (for example: no data to interpret).
    static_result: dict[str, Any] | None = None


@dataclass
class Finalized:
    result: dict[str, Any]
    evidence: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    description: str
    responsibility: str
    version: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    tools: tuple[str, ...]
    prepare: Callable[[AgentContext, ToolBox, Any], Prepared]
    finalize: Callable[[AgentContext, Prepared, Any], Finalized]
    required_role: str = "MEMBER"
    model: ModelConfig = field(default_factory=ModelConfig)
    limits: ExecutionLimits = field(default_factory=ExecutionLimits)


AGENTS: dict[str, AgentSpec] = {}


def validate_spec(spec: AgentSpec) -> None:
    if not KEY_PATTERN.fullmatch(spec.key) or spec.key == ORCHESTRATOR_KEY:
        raise InvalidAgentConfigError(f"Invalid agent key: {spec.key!r}.")
    if not VERSION_PATTERN.fullmatch(spec.version):
        raise InvalidAgentConfigError(f"Agent {spec.key}: version must look like 1.0.0.")
    if not spec.name.strip() or not spec.description.strip() or not spec.responsibility.strip():
        raise InvalidAgentConfigError(f"Agent {spec.key}: name, description and responsibility are required.")
    for model in (spec.input_model, spec.output_model):
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            raise InvalidAgentConfigError(f"Agent {spec.key}: input and output schemas must be Pydantic models.")
    unknown = [tool for tool in spec.tools if tool not in TOOLS]
    if unknown:
        raise InvalidAgentConfigError(f"Agent {spec.key}: unregistered tool(s) {', '.join(unknown)}.")
    if len(set(spec.tools)) != len(spec.tools):
        raise InvalidAgentConfigError(f"Agent {spec.key}: duplicate tools.")
    if spec.required_role not in ROLES:
        raise InvalidAgentConfigError(f"Agent {spec.key}: unknown role {spec.required_role}.")
    if not 0 <= spec.model.temperature <= 2 or not 1 <= spec.model.max_tokens <= 8192:
        raise InvalidAgentConfigError(f"Agent {spec.key}: model configuration is out of range.")
    limits = spec.limits
    if limits.timeout_seconds is not None and not 1 <= limits.timeout_seconds <= 600:
        raise InvalidAgentConfigError(f"Agent {spec.key}: timeout must be between 1 and 600 seconds.")
    if limits.max_attempts is not None and not 1 <= limits.max_attempts <= 6:
        raise InvalidAgentConfigError(f"Agent {spec.key}: max attempts must be between 1 and 6.")
    if not callable(spec.prepare) or not callable(spec.finalize):
        raise InvalidAgentConfigError(f"Agent {spec.key}: prepare and finalize must be callable.")


def register_agent(spec: AgentSpec, *, registry: dict[str, AgentSpec] | None = None) -> AgentSpec:
    target = AGENTS if registry is None else registry
    validate_spec(spec)
    if spec.key in target:
        raise InvalidAgentConfigError(f"Agent {spec.key} is already registered.")
    target[spec.key] = spec
    return spec


def get_agent(key: str, *, registry: dict[str, AgentSpec] | None = None) -> AgentSpec:
    target = AGENTS if registry is None else registry
    spec = target.get(key)
    if spec is None:
        raise UnknownAgentError(f"Agent '{key}' is not registered.")
    return spec


def list_agents() -> list[AgentSpec]:
    return list(AGENTS.values())


def disabled_agent_keys(db: DBSession, workspace_id: UUID) -> set[str]:
    rows = (
        db.query(AgentSetting.agent_key)
        .filter(AgentSetting.workspace_id == workspace_id, AgentSetting.enabled.is_(False))
        .all()
    )
    return {row.agent_key for row in rows}


def is_agent_enabled(db: DBSession, workspace_id: UUID, key: str) -> bool:
    return key not in disabled_agent_keys(db, workspace_id)


def require_enabled(db: DBSession, workspace_id: UUID, key: str) -> AgentSpec:
    spec = get_agent(key)
    if not is_agent_enabled(db, workspace_id, key):
        raise AgentDisabledError(f"The {spec.name} is disabled in this workspace.")
    return spec


def set_agent_enabled(db: DBSession, workspace_id: UUID, key: str, *, enabled: bool, user_id: UUID) -> AgentSetting:
    get_agent(key)
    setting = (
        db.query(AgentSetting)
        .filter(AgentSetting.workspace_id == workspace_id, AgentSetting.agent_key == key)
        .first()
    )
    if setting is None:
        setting = AgentSetting(workspace_id=workspace_id, agent_key=key)
        db.add(setting)
    setting.enabled = enabled
    setting.updated_by = user_id
    db.flush()
    return setting


def role_allows(role: str, required: str) -> bool:
    return ROLE_RANK.get(role, 0) >= ROLE_RANK.get(required, 99)


def describe_agent(spec: AgentSpec, *, enabled: bool = True) -> dict[str, Any]:
    return {
        "key": spec.key,
        "name": spec.name,
        "description": spec.description,
        "responsibility": spec.responsibility,
        "version": spec.version,
        "enabled": enabled,
        "required_role": spec.required_role,
        "tools": describe_tools(spec.tools),
        "model": {"provider": "groq", "temperature": spec.model.temperature, "max_tokens": spec.model.max_tokens},
        "limits": {"timeout_seconds": spec.limits.timeout_seconds, "max_attempts": spec.limits.max_attempts},
        "input_schema": spec.input_model.model_json_schema(),
        "output_schema": spec.output_model.model_json_schema(),
    }
