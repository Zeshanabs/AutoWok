"""Live web search for the research engine.

``RESEARCH_SEARCH_PROVIDER`` selects the service and ``RESEARCH_SEARCH_API_KEY``
authenticates to it. Supported providers:

* ``groq``:   Groq's built-in web search tool, using a Groq API key. One search
  uses many thousands of Groq tokens, which count against the same Groq limits
  as the AI features.
* ``tavily``: https://tavily.com (search API built for AI research)
* ``brave``:  https://brave.com/search/api (independent web index)

The key is sent only to the provider's official host unless
``RESEARCH_SEARCH_BASE_URL`` is set, and it never appears in an error message.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.integrations.research.base import SearchProviderConfig, SearchProviderRegistry, SearchResult

SUPPORTED_PROVIDERS = ("groq", "tavily", "brave")
_DEFAULT_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "tavily": "https://api.tavily.com",
    "brave": "https://api.search.brave.com",
}
# Groq's built-in web search runs inside a chat completion on these models.
GROQ_SEARCH_MODEL = "openai/gpt-oss-20b"
_GROQ_SEARCH_INSTRUCTIONS = (
    "You are a web search step. Call browser.search exactly once with the user's query. "
    "Do not open pages and do not search again. Then reply with only a JSON array, one object per "
    "search result, with keys: title, url, summary. The summary is one sentence taken from the "
    "search result text; use an empty string when the result has no text. No other output."
)
_MAX_QUERY_CHARS = 400
_MAX_QUERY_WORDS = 50
_MAX_RESULTS_PER_REQUEST = 20


def _clean_query(query: str) -> str:
    words = " ".join(query.split())[:_MAX_QUERY_CHARS].split()
    return " ".join(words[:_MAX_QUERY_WORDS])


def _parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _result(provider: str, *, title: Any, url: Any, snippet: Any, published: Any) -> SearchResult | None:
    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()
    domain = (urlsplit(url).hostname or "").lower()
    if not domain:
        return None
    text = " ".join(str(snippet).split())[:2000] if snippet else None
    return SearchResult(
        title=(" ".join(str(title).split()) if title else domain)[:500],
        url=url,
        domain=domain,
        snippet=text,
        publication_date=_parse_date(published),
        provider=provider,
    )


class ConfiguredSearchProvider:
    name = "configured"

    def __init__(self, config: SearchProviderConfig | None = None, *, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config or SearchProviderConfig(name="configured")
        self._transport = transport

    def _base_url(self, provider: str) -> str:
        base_url = (self.config.base_url or "").strip().rstrip("/")
        if not base_url or base_url == "https://example.com":
            return _DEFAULT_BASE_URLS[provider]
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise RuntimeError("RESEARCH_SEARCH_BASE_URL must be an https address.")
        return base_url

    def _send(self, method: str, url: str, *, timeout_seconds: int, **kwargs: Any) -> dict[str, Any]:
        provider = self.config.name
        try:
            with httpx.Client(timeout=timeout_seconds, trust_env=False, transport=self._transport) as client:
                response = client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"The {provider} search provider did not answer in time.") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"The {provider} search provider could not be reached.") from exc
        if response.status_code in {401, 403}:
            raise RuntimeError(f"The {provider} search provider rejected the API key. Check RESEARCH_SEARCH_API_KEY.")
        if response.status_code == 429:
            raise RuntimeError(f"The {provider} search provider's rate limit or quota is used up. Try again later.")
        if response.status_code >= 400:
            raise RuntimeError(f"The {provider} search provider returned an error (status {response.status_code}).")
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"The {provider} search provider returned an unreadable answer.") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"The {provider} search provider returned an unexpected answer.")
        return data

    def _search_groq(self, query: str, max_results: int, timeout_seconds: int) -> list[SearchResult]:
        """Web search through Groq's built-in ``browser_search`` tool.

        Sources are taken only from the search the tool actually executed, so a
        made-up address in the model's text can never become a source. The
        model's text only supplies the one-sentence summaries.
        """
        data = self._send(
            "POST",
            f"{self._base_url('groq')}/chat/completions",
            timeout_seconds=max(timeout_seconds, 90),
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            json={
                "model": GROQ_SEARCH_MODEL,
                "messages": [
                    {"role": "system", "content": _GROQ_SEARCH_INSTRUCTIONS},
                    {"role": "user", "content": query},
                ],
                "tools": [{"type": "browser_search"}],
                "reasoning_effort": "low",
                "temperature": 0,
                "max_completion_tokens": 2500,
            },
        )
        choices = data.get("choices")
        message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise RuntimeError("The groq search provider returned an unexpected answer.")

        summaries: dict[str, str] = {}
        content = message.get("content")
        if isinstance(content, str) and "[" in content and "]" in content:
            try:
                rows = json.loads(content[content.index("[") : content.rindex("]") + 1])
            except ValueError:
                rows = []
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict) and isinstance(row.get("url"), str) and isinstance(row.get("summary"), str):
                    summaries[row["url"].strip().rstrip("/")] = row["summary"]

        results: list[SearchResult] = []
        seen: set[str] = set()
        tools = message.get("executed_tools")
        for tool in tools if isinstance(tools, list) else []:
            found = tool.get("search_results") if isinstance(tool, dict) else None
            rows = found.get("results") if isinstance(found, dict) else None
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict) or not isinstance(row.get("url"), str):
                    continue
                key = row["url"].strip().rstrip("/")
                if key in seen:
                    continue
                entry = _result("groq", title=row.get("title"), url=row["url"], snippet=row.get("content") or summaries.get(key), published=None)
                if entry is not None:
                    seen.add(key)
                    results.append(entry)
                if len(results) >= max_results:
                    return results
        return results

    def _search_tavily(self, query: str, max_results: int, timeout_seconds: int) -> list[SearchResult]:
        data = self._send(
            "POST",
            f"{self._base_url('tavily')}/search",
            timeout_seconds=timeout_seconds,
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            json={"query": query, "max_results": max_results, "search_depth": "basic"},
        )
        rows = data.get("results")
        results = [
            _result("tavily", title=row.get("title"), url=row.get("url"), snippet=row.get("content"), published=row.get("published_date"))
            for row in (rows if isinstance(rows, list) else [])
            if isinstance(row, dict)
        ]
        return [entry for entry in results if entry is not None]

    def _search_brave(self, query: str, max_results: int, timeout_seconds: int) -> list[SearchResult]:
        data = self._send(
            "GET",
            f"{self._base_url('brave')}/res/v1/web/search",
            timeout_seconds=timeout_seconds,
            headers={"X-Subscription-Token": self.config.api_key or "", "Accept": "application/json"},
            params={"q": query, "count": max_results},
        )
        web = data.get("web")
        rows = web.get("results") if isinstance(web, dict) else None
        results = [
            _result("brave", title=row.get("title"), url=row.get("url"), snippet=row.get("description"), published=row.get("page_age"))
            for row in (rows if isinstance(rows, list) else [])
            if isinstance(row, dict)
        ]
        return [entry for entry in results if entry is not None]

    def search(self, query: str, *, max_results: int = 10, timeout_seconds: int = 30) -> list[SearchResult]:
        if not self.config.api_key:
            raise RuntimeError(
                "The configured research search provider is not set up. Add RESEARCH_SEARCH_PROVIDER and RESEARCH_SEARCH_API_KEY."
            )
        provider = (self.config.name or "").strip().lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise RuntimeError(
                f"Research search provider '{provider or 'none'}' is not supported. "
                f"Set RESEARCH_SEARCH_PROVIDER to one of: {', '.join(SUPPORTED_PROVIDERS)}."
            )
        cleaned = _clean_query(query)
        if not cleaned:
            return []
        limit = max(1, min(int(max_results), _MAX_RESULTS_PER_REQUEST))
        if provider == "groq":
            return self._search_groq(cleaned, limit, timeout_seconds)
        if provider == "tavily":
            return self._search_tavily(cleaned, limit, timeout_seconds)
        return self._search_brave(cleaned, limit, timeout_seconds)


SearchProviderRegistry.register(ConfiguredSearchProvider)
