from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.orm import Session as DBSession

from app.core.config import Settings, get_settings
from app.models import AIProviderConfig
from app.services.ai_encryption import EncryptionNotConfigured, decrypt_api_key

MAX_PROMPT_CHARACTERS = 32_000
MAX_COMPLETION_TOKENS = 8_192
RETRYABLE_STATUSES = {500, 502, 503, 504}


class GroqError(RuntimeError):
    status_code = 502


class GroqNotConfiguredError(GroqError):
    status_code = 503


class GroqAuthenticationError(GroqError):
    status_code = 401


class GroqRateLimitError(GroqError):
    status_code = 429

    def __init__(self, retry_after: str | None = None) -> None:
        self.retry_after = retry_after
        super().__init__("Groq's rate limit has been reached. Wait for it to reset and try again.")


class GroqRequestError(GroqError):
    status_code = 422


class GroqTimeoutError(GroqError):
    status_code = 504


class GroqUnavailableError(GroqError):
    status_code = 502


@dataclass(frozen=True)
class GroqCredential:
    api_key: str
    model: str
    source: str
    config: AIProviderConfig | None


@dataclass(frozen=True)
class GroqUsage:
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


@dataclass(frozen=True)
class GroqCompletion:
    text: str
    model: str
    usage: GroqUsage | None


class GroqService:
    def __init__(
        self,
        db: DBSession,
        workspace_id: UUID,
        *,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
        jitter=random.uniform,
    ) -> None:
        self._db = db
        self._workspace_id = workspace_id
        self._settings = settings or get_settings()
        self._transport = transport
        self._sleep = sleep
        self._jitter = jitter
        self._last_usage: GroqUsage | None = None
        self._preloaded: GroqCredential | None = None

    def preload_credential(self) -> None:
        """Resolve the credential now so later completions do not use the database.

        Phase 11 runs agent completions on worker threads; a SQLAlchemy session
        must not be shared between threads, so the lookup happens up front.
        """
        self._preloaded = self._credential()

    def configuration_status(self) -> dict[str, Any]:
        provider = self._workspace_config()
        enabled = self._settings.groq_enabled
        if provider is not None:
            return {
                "enabled": enabled and provider.is_active,
                "configured": bool(provider.encrypted_api_key),
                "source": "workspace",
                "model_name": provider.model_name,
                "api_key_configured": bool(provider.encrypted_api_key),
            }
        return {
            "enabled": enabled,
            "configured": bool(self._settings.groq_api_key.strip()),
            "source": "environment" if self._settings.groq_api_key.strip() else "missing",
            "model_name": self._settings.groq_default_model or None,
            "api_key_configured": bool(self._settings.groq_api_key.strip()),
        }

    def _workspace_config(self) -> AIProviderConfig | None:
        return (
            self._db.query(AIProviderConfig)
            .filter(
                AIProviderConfig.workspace_id == self._workspace_id,
                AIProviderConfig.provider_name == "groq",
            )
            .first()
        )

    def _credential(self, *, require_model: bool = True) -> GroqCredential:
        if self._preloaded is not None:
            return self._preloaded
        if not self._settings.groq_enabled:
            raise GroqNotConfiguredError("Groq is disabled by the server configuration.")
        provider = self._workspace_config()
        if provider is not None:
            if not provider.is_active:
                raise GroqNotConfiguredError("The workspace Groq provider is disabled.")
            if not provider.encrypted_api_key:
                raise GroqNotConfiguredError("No Groq API key is configured for this workspace.")
            try:
                api_key = decrypt_api_key(provider.encrypted_api_key)
            except EncryptionNotConfigured as exc:
                raise GroqNotConfiguredError(
                    "The saved Groq key cannot be decrypted. Check AI_ENCRYPTION_KEY."
                ) from exc
            return GroqCredential(api_key, provider.model_name, "workspace", provider)

        api_key = self._settings.groq_api_key.strip()
        if not api_key:
            raise GroqNotConfiguredError(
                "Groq is not configured. Add a workspace API key or configure GROQ_API_KEY."
            )
        if require_model and not self._settings.groq_default_model.strip():
            raise GroqNotConfiguredError(
                "Set GROQ_DEFAULT_MODEL or configure a workspace model before using Groq."
            )
        return GroqCredential(
            api_key,
            self._settings.groq_default_model.strip(),
            "environment",
            None,
        )

    def list_models(self) -> list[str]:
        credential = self._credential(require_model=False)
        body = self._request(
            "GET",
            "/models",
            credential,
            retry_transient=True,
        )
        data = body.get("data")
        if not isinstance(data, list):
            raise GroqUnavailableError("Groq returned an invalid models response.")
        return sorted(
            {
                item["id"]
                for item in data
                if isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and item["id"]
            }
        )

    def test_connection(self, model: str | None = None) -> dict[str, str]:
        credential = self._credential()
        models = self._request(
            "GET",
            "/models",
            credential,
            retry_transient=True,
        )
        available = {
            item["id"]
            for item in models.get("data", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        selected_model = model or credential.model
        if selected_model not in available:
            raise GroqRequestError(
                "The configured Groq model is not available to this account. Choose a model from the current model list."
            )
        return {"status": "success", "model": selected_model}

    def generate_completion(
        self,
        prompt: str,
        *,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> GroqCompletion:
        if not isinstance(prompt, str) or not prompt.strip():
            raise GroqRequestError("Enter a non-empty prompt.")
        if len(prompt) > MAX_PROMPT_CHARACTERS:
            raise GroqRequestError(
                f"The prompt must be at most {MAX_PROMPT_CHARACTERS} characters."
            )
        if not 1 <= max_tokens <= MAX_COMPLETION_TOKENS:
            raise GroqRequestError(
                f"max_tokens must be between 1 and {MAX_COMPLETION_TOKENS}."
            )
        if not 0 <= temperature <= 2:
            raise GroqRequestError("temperature must be between 0 and 2.")
        credential = self._credential()
        selected_model = model or credential.model
        body = self._request(
            "POST",
            "/chat/completions",
            credential,
            json={
                "model": selected_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            },
            retry_transient=False,
        )
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise GroqUnavailableError("Groq returned no completion choices.")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise GroqUnavailableError("Groq returned an invalid completion.")
        usage = body.get("usage")
        self._last_usage = (
            GroqUsage(
                prompt_tokens=usage.get("prompt_tokens")
                if isinstance(usage, dict) and isinstance(usage.get("prompt_tokens"), int)
                else None,
                completion_tokens=usage.get("completion_tokens")
                if isinstance(usage, dict)
                and isinstance(usage.get("completion_tokens"), int)
                else None,
                total_tokens=usage.get("total_tokens")
                if isinstance(usage, dict) and isinstance(usage.get("total_tokens"), int)
                else None,
            )
            if isinstance(usage, dict)
            else None
        )
        return GroqCompletion(
            text=text,
            model=body.get("model")
            if isinstance(body.get("model"), str)
            else selected_model,
            usage=self._last_usage,
        )

    def get_usage_information(self) -> GroqUsage | None:
        return self._last_usage

    def _request(
        self,
        method: str,
        path: str,
        credential: GroqCredential,
        *,
        json: dict[str, Any] | None = None,
        retry_transient: bool,
    ) -> dict[str, Any]:
        attempts = self._settings.groq_max_retries if retry_transient else 0
        with httpx.Client(
            base_url=self._settings.groq_api_base_url,
            timeout=self._settings.groq_timeout_seconds,
            follow_redirects=False,
            trust_env=self._transport is None,
            transport=self._transport,
        ) as client:
            for attempt in range(attempts + 1):
                try:
                    response = client.request(
                        method,
                        path,
                        headers={"Authorization": f"Bearer {credential.api_key}"},
                        json=json,
                    )
                except httpx.TimeoutException as exc:
                    if attempt < attempts:
                        self._backoff(attempt)
                        continue
                    raise GroqTimeoutError(
                        "Groq did not respond before the configured timeout."
                    ) from exc
                except httpx.HTTPError as exc:
                    if attempt < attempts:
                        self._backoff(attempt)
                        continue
                    raise GroqUnavailableError(
                        "Groq could not be reached. Check the connection and try again."
                    ) from exc

                if response.status_code == 429:
                    raise GroqRateLimitError(response.headers.get("Retry-After"))
                if response.status_code in {401, 403}:
                    raise GroqAuthenticationError(
                        "Groq rejected the API key or account permissions."
                    )
                if response.status_code in RETRYABLE_STATUSES:
                    if attempt < attempts:
                        self._backoff(attempt)
                        continue
                    raise GroqUnavailableError(
                        "Groq is temporarily unavailable. Try again later."
                    )
                if response.status_code >= 400:
                    raise GroqRequestError(
                        "Groq rejected the request. Check the model and request settings."
                    )
                try:
                    result = response.json()
                except ValueError as exc:
                    raise GroqUnavailableError("Groq returned an invalid response.") from exc
                if not isinstance(result, dict):
                    raise GroqUnavailableError("Groq returned an invalid response.")
                return result
        raise GroqUnavailableError("Groq could not complete the request.")

    def _backoff(self, attempt: int) -> None:
        delay = min(8.0, 0.5 * (2**attempt)) + self._jitter(0.0, 0.25)
        self._sleep(delay)
