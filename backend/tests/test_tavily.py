"""Offline unit tests for the Tavily web-search adapter (no network)."""

from __future__ import annotations

import pytest

from app.integrations.tavily import TavilyWebSearch
from app.integrations.websearch import SearchResult, WebSearchError, get_web_search


def test_parse_maps_results():
    body = {
        "results": [
            {"title": "Foo", "url": "https://foo.test", "content": "about foo"},
            {"title": "Bar", "url": "https://bar.test", "content": "about bar"},
        ]
    }
    results = TavilyWebSearch._parse(body)
    assert results == [
        SearchResult(title="Foo", url="https://foo.test", snippet="about foo"),
        SearchResult(title="Bar", url="https://bar.test", snippet="about bar"),
    ]


def test_parse_tolerates_missing_fields_and_empty():
    assert TavilyWebSearch._parse({}) == []
    # Missing title falls back to the url; missing content -> empty snippet.
    [only] = TavilyWebSearch._parse({"results": [{"url": "https://x.test"}]})
    assert only.title == "https://x.test"
    assert only.snippet == ""


@pytest.mark.asyncio
async def test_missing_key_raises_without_network():
    client = TavilyWebSearch(api_key="")  # explicit empty -> no settings, no HTTP
    with pytest.raises(WebSearchError):
        await client.search("anything")


def test_resolver_selects_tavily():
    assert isinstance(get_web_search("tavily"), TavilyWebSearch)
