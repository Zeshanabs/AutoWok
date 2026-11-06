from __future__ import annotations

from urllib.parse import urlsplit

from app.integrations.research.base import SearchProviderConfig, SearchProviderRegistry, SearchResult


class ConfiguredSearchProvider:
    name = "configured"

    def __init__(self, config: SearchProviderConfig | None = None) -> None:
        self.config = config or SearchProviderConfig(name="configured")

    def search(self, query: str, *, max_results: int = 10, timeout_seconds: int = 30) -> list[SearchResult]:
        if not self.config.api_key:
            raise RuntimeError(
                "The configured research search provider is not set up. Add RESEARCH_SEARCH_PROVIDER and RESEARCH_SEARCH_API_KEY."
            )
        if not self.config.base_url:
            raise RuntimeError("The research provider base URL is missing. Set RESEARCH_SEARCH_BASE_URL.")
        parsed = urlsplit(self.config.base_url)
        if not parsed.scheme or not parsed.netloc:
            raise RuntimeError("The research provider base URL is invalid.")
        if self.config.name == "configured":
            raise RuntimeError(
                "No supported live search provider is configured. Add a real search provider and credentials before running research."
            )
        return []


SearchProviderRegistry.register(ConfiguredSearchProvider)
