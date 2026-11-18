"""Live research search providers (Tavily, Brave).

Every provider call here is answered by a scripted HTTP transport. These tests
verify request building, response parsing and error handling. They do NOT
verify a live Tavily or Brave account.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import get_settings
from app.integrations.research.base import SearchProviderConfig, SearchResult
from app.integrations.research.providers.search_provider import ConfiguredSearchProvider
from tests.publishing_helpers import CSRF, PASSWORD

API = "/api/v1"
SECRET = "search-secret-key-000111"


def provider(name: str, handler, **config) -> ConfiguredSearchProvider:
    return ConfiguredSearchProvider(
        SearchProviderConfig(name=name, api_key=SECRET, **config), transport=httpx.MockTransport(handler)
    )


def test_tavily_request_and_parsing():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "Home brewing trends", "url": "https://news.example.com/brewing", "content": "Home  brewing\nkeeps growing.", "published_date": "2026-10-01T08:00:00Z"},
                    {"title": "No address"},
                    "not a row",
                ]
            },
        )

    results = provider("tavily", handler).search("  home   brewing  ", max_results=5)
    assert seen["url"] == "https://api.tavily.com/search"
    assert seen["auth"] == f"Bearer {SECRET}"
    assert seen["body"] == {"query": "home brewing", "max_results": 5, "search_depth": "basic"}
    assert len(results) == 1
    only = results[0]
    assert (only.title, only.url, only.domain, only.provider) == ("Home brewing trends", "https://news.example.com/brewing", "news.example.com", "tavily")
    assert only.snippet == "Home brewing keeps growing." and only.publication_date.year == 2026


def test_brave_request_and_parsing():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["host"] = request.url.host
        seen["params"] = dict(request.url.params)
        seen["token"] = request.headers["x-subscription-token"]
        return httpx.Response(200, json={"web": {"results": [{"title": "Guide", "url": "https://blog.example.org/guide", "description": "A guide.", "page_age": "not a date"}]}})

    results = provider("brave", handler).search("coffee", max_results=50)
    assert (seen["host"], seen["path"]) == ("api.search.brave.com", "/res/v1/web/search")
    assert seen["params"] == {"q": "coffee", "count": "20"}  # capped at the provider maximum
    assert seen["token"] == SECRET
    assert results[0].domain == "blog.example.org" and results[0].publication_date is None and results[0].provider == "brave"


def test_groq_sources_come_only_from_the_executed_search():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        answer = json.dumps(
            [
                {"title": "Espresso", "url": "https://news.example.com/espresso/", "summary": "Home espresso is growing."},
                {"title": "Invented", "url": "https://made-up.example.net/page", "summary": "Not a real search result."},
            ]
        )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": f"Here you go:\n{answer}",
                            "executed_tools": [
                                {
                                    "type": "browser_search",
                                    "search_results": {
                                        "results": [
                                            {"title": "A new era of home espresso", "url": "https://news.example.com/espresso", "content": "", "score": 0},
                                            {"title": "Trends", "url": "https://blog.example.org/trends", "content": "", "score": 0},
                                            {"title": "A new era of home espresso", "url": "https://news.example.com/espresso", "content": "", "score": 0},
                                        ]
                                    },
                                },
                                {"type": "browser_open", "output": "page text"},
                            ],
                        }
                    }
                ]
            },
        )

    results = provider("groq", handler).search("home espresso", max_results=10)
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions" and seen["auth"] == f"Bearer {SECRET}"
    assert seen["body"]["tools"] == [{"type": "browser_search"}] and seen["body"]["messages"][-1] == {"role": "user", "content": "home espresso"}
    assert [(item.url, item.snippet, item.provider) for item in results] == [
        ("https://news.example.com/espresso", "Home espresso is growing.", "groq"),
        ("https://blog.example.org/trends", None, "groq"),
    ]


def test_groq_answer_without_a_search_gives_no_sources():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": '[{"title": "x", "url": "https://made-up.example.net", "summary": "y"}]'}}]})

    assert provider("groq", handler).search("coffee") == []


def test_long_question_is_shortened_for_the_provider():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = json.loads(request.content)["query"]
        return httpx.Response(200, json={"results": []})

    assert provider("tavily", handler).search("word " * 500) == []
    assert len(seen["query"]) <= 400 and len(seen["query"].split()) <= 50


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(401, "rejected the API key"), (403, "rejected the API key"), (429, "rate limit or quota"), (500, "status 500")],
)
def test_provider_errors_are_readable_and_never_contain_the_key(status_code, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"detail": f"bad key {SECRET}"})

    with pytest.raises(RuntimeError) as error:
        provider("tavily", handler).search("coffee")
    assert expected in str(error.value) and SECRET not in str(error.value)


def test_network_failure_and_bad_answers_are_handled():
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    def not_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>")

    with pytest.raises(RuntimeError, match="could not be reached"):
        provider("brave", unreachable).search("coffee")
    with pytest.raises(RuntimeError, match="did not answer in time"):
        provider("brave", slow).search("coffee")
    with pytest.raises(RuntimeError, match="unreadable"):
        provider("brave", not_json).search("coffee")


def test_unsupported_provider_missing_key_and_bad_base_url():
    def never(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request expected")

    with pytest.raises(RuntimeError, match="not supported.*tavily, brave"):
        provider("google", never).search("coffee")
    with pytest.raises(RuntimeError, match="not set up"):
        ConfiguredSearchProvider(SearchProviderConfig(name="tavily"), transport=httpx.MockTransport(never)).search("coffee")
    with pytest.raises(RuntimeError, match="https address"):
        provider("tavily", never, base_url="http://search.internal").search("coffee")


# Through the API ------------------------------------------------------------------------


def _project(client_factory):
    client = client_factory()
    registered = client.post(
        f"{API}/auth/register", json={"full_name": "Rita Researcher", "email": "rita@example.com", "password": PASSWORD}, headers=CSRF
    )
    assert registered.status_code == 201, registered.text
    workspace_id = registered.json()["workspace"]["id"]
    created = client.post(
        f"{API}/research",
        json={"workspace_id": workspace_id, "title": "Home coffee habits", "research_question": "What do home brewers struggle with?"},
        headers=CSRF,
    )
    assert created.status_code == 201, created.text
    return client, created.json()["id"]


def _configure(monkeypatch, name: str = "tavily") -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "research_search_provider", name)
    monkeypatch.setattr(settings, "research_search_api_key", SECRET)
    monkeypatch.setattr(settings, "research_search_base_url", "")


def test_run_stores_sources_findings_and_a_report_and_can_be_repeated(client_factory, monkeypatch):
    client, research_id = _project(client_factory)
    _configure(monkeypatch)

    def fake_search(self, query: str, *, max_results: int = 10, timeout_seconds: int = 30):
        return [
            SearchResult(title="Grind size", url="https://news.example.com/grind", domain="news.example.com", snippet="Most home brewers grind too fine.", provider="tavily"),
            SearchResult(title="Water", url="https://blog.example.org/water", domain="blog.example.org", snippet=None, provider="tavily"),
            SearchResult(title="Internal", url="http://127.0.0.1/admin", domain="127.0.0.1", snippet="x", provider="tavily"),
        ]

    monkeypatch.setattr(ConfiguredSearchProvider, "search", fake_search)
    for _attempt in range(2):  # the second run replaces the first, without duplicates
        ran = client.post(f"{API}/research/{research_id}/run", headers=CSRF)
        assert ran.status_code == 200, ran.text
        assert ran.json()["status"] == "COMPLETED"
        sources = client.get(f"{API}/research/{research_id}/sources").json()
        assert sorted(item["url"] for item in sources) == ["https://blog.example.org/water", "https://news.example.com/grind"]
        findings = client.get(f"{API}/research/{research_id}/findings").json()
        assert [item["claim"] for item in findings] == ["Most home brewers grind too fine."]
        grind = next(item for item in sources if item["url"].endswith("/grind"))
        assert findings[0]["supporting_source_ids"] == [grind["id"]] and findings[0]["confidence_label"] == "LOW"
        report = client.get(f"{API}/research/{research_id}/report").json()
        assert "Found 2 sources from 2 websites" in report["executive_summary"]
        assert report["key_findings"] == ["Grind size (news.example.com): Most home brewers grind too fine."]
        assert any("not been fact-checked" in line for line in report["limitations"])
    assert SECRET not in ran.text


def test_run_with_no_results_says_so(client_factory, monkeypatch):
    client, research_id = _project(client_factory)
    _configure(monkeypatch, "brave")
    monkeypatch.setattr(ConfiguredSearchProvider, "search", lambda self, query, **_kwargs: [])
    assert client.post(f"{API}/research/{research_id}/run", headers=CSRF).status_code == 200
    report = client.get(f"{API}/research/{research_id}/report").json()
    assert "returned no usable sources" in report["executive_summary"] and report["key_findings"] == []
    assert client.get(f"{API}/research/{research_id}/findings").json() == []


def test_provider_failure_marks_the_run_failed_with_a_clear_message(client_factory, monkeypatch):
    client, research_id = _project(client_factory)
    _configure(monkeypatch)

    def failing(self, query: str, **_kwargs):
        raise RuntimeError("The tavily search provider rejected the API key. Check RESEARCH_SEARCH_API_KEY.")

    monkeypatch.setattr(ConfiguredSearchProvider, "search", failing)
    ran = client.post(f"{API}/research/{research_id}/run", headers=CSRF)
    assert ran.status_code == 502 and "rejected the API key" in ran.text and SECRET not in ran.text
    assert client.get(f"{API}/research/{research_id}/status").json()["status"] == "FAILED"


def test_unsupported_provider_name_is_reported(client_factory, monkeypatch):
    client, research_id = _project(client_factory)
    _configure(monkeypatch, "google")
    ran = client.post(f"{API}/research/{research_id}/run", headers=CSRF)
    assert ran.status_code == 502 and "tavily, brave" in ran.json()["detail"]
