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
        if not query or not query.strip():
            return []
        parsed = urlsplit(self.config.base_url or "https://example.com")
        if not parsed.scheme or not parsed.netloc:
            raise RuntimeError("The research provider base URL is invalid.")
        return [
            SearchResult(
                title=f"{query.strip()} results",
                url=f"https://example.com/search?q={query.strip()}",
                domain="example.com",
                snippet="Provider configuration is present, but this environment is not configured for live external search.",
                provider=self.name,
            )
        ][:max_results]


SearchProviderRegistry.register(ConfiguredSearchProvider)
