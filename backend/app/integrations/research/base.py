from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    domain: str
    snippet: str | None = None
    publication_date: datetime | None = None
    provider: str = "custom"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchProviderConfig:
    name: str
    api_key: str | None = None
    base_url: str | None = None
    max_results: int = 10
    timeout_seconds: int = 30


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, max_results: int = 10, timeout_seconds: int = 30) -> list[SearchResult]:
        ...


class SearchProviderRegistry:
    _providers: dict[str, type[SearchProvider]] = {}

    @classmethod
    def register(cls, provider: type[SearchProvider]) -> type[SearchProvider]:
        cls._providers[provider.name] = provider
        return provider

    @classmethod
    def get(cls, name: str) -> type[SearchProvider]:
        try:
            return cls._providers[name]
        except KeyError as exc:
            raise ValueError(f"Unknown search provider: {name}") from exc

    @classmethod
    def names(cls) -> list[str]:
        return sorted(cls._providers)
