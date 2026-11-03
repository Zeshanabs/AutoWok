from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Protocol
from urllib.parse import urlsplit

import httpcore
import httpx

from app.core.config import get_settings
from app.schemas.brands import ProviderName


class _PinnedNetworkBackend(httpcore.NetworkBackend):
    def __init__(self, host: str, addresses: tuple[str, ...]) -> None:
        self._host = host.lower().rstrip(".")
        self._addresses = addresses
        self._backend = httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[tuple[int, int, int]] | None = None,
    ) -> httpcore.NetworkStream:
        if host.lower().rstrip(".") != self._host or port != 443:
            raise httpcore.ConnectError("Connection target does not match the pinned host.")
        last_error: httpcore.ConnectError | None = None
        for address in self._addresses:
            try:
                return self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except httpcore.ConnectError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise httpcore.ConnectError("The pinned host has no validated addresses.")

    def sleep(self, seconds: float) -> None:
        self._backend.sleep(seconds)


class PinnedHTTPTransport(httpx.HTTPTransport):
    def __init__(self, host: str, addresses: tuple[str, ...]) -> None:
        super().__init__(trust_env=False)
        self._pool.close()
        self._pool = httpcore.ConnectionPool(
            network_backend=_PinnedNetworkBackend(host, addresses),
            max_connections=1,
            max_keepalive_connections=0,
        )


class ProviderTestStatus(StrEnum):
    SUCCESS = "success"
    INVALID_CREDENTIALS = "invalid_credentials"
    QUOTA_EXCEEDED = "quota_exceeded"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    FAILED = "failed"


@dataclass(frozen=True)
class ProviderTestResult:
    status: ProviderTestStatus
    message: str


class AIProviderAdapter(Protocol):
    name: ProviderName

    def validate_configuration(self, *, base_url: str | None) -> str | None: ...

    def test_connection(
        self,
        *,
        api_key: str,
        base_url: str | None,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderTestResult: ...

    def get_available_models(self, *, api_key: str) -> list[str]: ...

    def generate_response(self, *, api_key: str, prompt: str) -> str: ...


@dataclass(frozen=True)
class ProviderAdapter:
    name: ProviderName
    default_base_url: str
    auth_header: str
    auth_scheme: str

    def validate_configuration(self, *, base_url: str | None) -> str | None:
        return validate_provider_endpoint(self.name, base_url)

    def test_connection(
        self,
        *,
        api_key: str,
        base_url: str | None,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderTestResult:
        selected_base = base_url.rstrip("/") if base_url else self.default_base_url
        url = f"{selected_base}/models"
        headers = {"Accept": "application/json", "User-Agent": "Autowok/Phase2"}
        auth_value = f"{self.auth_scheme}{api_key}" if self.auth_scheme else api_key
        headers[self.auth_header] = auth_value
        if self.name == ProviderName.ANTHROPIC:
            headers["anthropic-version"] = "2023-06-01"

        try:
            with httpx.Client(
                timeout=timeout_seconds,
                follow_redirects=False,
                trust_env=transport is None,
                transport=transport,
            ) as client:
                response = client.get(url, headers=headers)
        except httpx.TimeoutException:
            return ProviderTestResult(
                ProviderTestStatus.TIMEOUT,
                "The provider did not respond before the connection timeout.",
            )
        except httpx.HTTPError:
            return ProviderTestResult(
                ProviderTestStatus.PROVIDER_UNAVAILABLE,
                "The provider could not be reached. Check the endpoint and try again.",
            )

        if 200 <= response.status_code < 300:
            return ProviderTestResult(
                ProviderTestStatus.SUCCESS, "The provider connection succeeded."
            )
        if response.status_code in {401, 403}:
            return ProviderTestResult(
                ProviderTestStatus.INVALID_CREDENTIALS,
                "The provider rejected the credentials or account permissions.",
            )
        if response.status_code in {402, 429}:
            return ProviderTestResult(
                ProviderTestStatus.QUOTA_EXCEEDED,
                "The provider reported a quota or rate limit issue.",
            )
        return ProviderTestResult(
            ProviderTestStatus.PROVIDER_UNAVAILABLE,
            "The provider returned an unsuccessful response. Check its status and try again.",
        )


PROVIDER_REGISTRY: dict[ProviderName, ProviderAdapter] = {
    ProviderName.OPENAI: ProviderAdapter(
        ProviderName.OPENAI, "https://api.openai.com/v1", "Authorization", "Bearer "
    ),
    ProviderName.ANTHROPIC: ProviderAdapter(
        ProviderName.ANTHROPIC, "https://api.anthropic.com/v1", "x-api-key", ""
    ),
    ProviderName.GEMINI: ProviderAdapter(
        ProviderName.GEMINI,
        "https://generativelanguage.googleapis.com/v1beta",
        "x-goog-api-key",
        "",
    ),
    ProviderName.GROQ: ProviderAdapter(
        ProviderName.GROQ,
        "https://api.groq.com/openai/v1",
        "Authorization",
        "Bearer ",
    ),
    ProviderName.OPENAI_COMPATIBLE: ProviderAdapter(
        ProviderName.OPENAI_COMPATIBLE, "", "Authorization", "Bearer "
    ),
}


def validate_provider_endpoint(
    provider_name: ProviderName,
    base_url: str | None,
) -> str | None:
    if provider_name != ProviderName.OPENAI_COMPATIBLE:
        if base_url is not None:
            raise ValueError("A custom base URL is only supported for OpenAI-compatible providers.")
        return None

    if base_url is None:
        raise ValueError("A base URL is required for a custom OpenAI-compatible provider.")
    parsed = urlsplit(base_url)
    try:
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The custom provider URL is invalid.") from exc
    settings = get_settings()
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or any(part in {".", ".."} for part in parsed.path.split("/"))
        or host not in settings.ai_custom_endpoint_hosts_list
    ):
        raise ValueError(
            "Custom endpoints must use HTTPS on port 443 and a host in AI_CUSTOM_ENDPOINT_HOSTS."
        )
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("Custom endpoint hosts must be allowlisted DNS names, not IP addresses.")
    return f"https://{host}{parsed.path.rstrip('/')}"


def validate_public_custom_endpoint(base_url: str) -> tuple[str, ...]:
    parsed = urlsplit(base_url)
    host = parsed.hostname
    if not host:
        raise ValueError("The custom provider host is invalid.")
    try:
        addresses = {
            entry[4][0]
            for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise ValueError("The custom provider host could not be resolved.") from exc
    if not addresses:
        raise ValueError("The custom provider host did not resolve to an address.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("The custom provider host resolves to a non-public network address.")
    return tuple(sorted(addresses))
