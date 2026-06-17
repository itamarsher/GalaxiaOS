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


def test_usage_credits_extracts_measured_consumption():
    # Basic search reports 1 credit, advanced 2; we read it verbatim.
    assert TavilyWebSearch._usage_credits({"usage": {"credits": 1}}) == 1
    assert TavilyWebSearch._usage_credits({"usage": {"credits": 2}}) == 2


def test_usage_credits_is_none_when_absent_or_malformed():
    # ``include_usage`` omitted, or a non-conforming block -> fall back to estimate.
    assert TavilyWebSearch._usage_credits({}) is None
    assert TavilyWebSearch._usage_credits({"usage": None}) is None
    assert TavilyWebSearch._usage_credits({"usage": {}}) is None
    assert TavilyWebSearch._usage_credits({"usage": {"credits": "1"}}) is None


@pytest.mark.asyncio
async def test_missing_key_raises_without_network():
    client = TavilyWebSearch(api_key="")  # explicit empty -> no settings, no HTTP
    with pytest.raises(WebSearchError):
        await client.search("anything")


def test_resolver_selects_tavily():
    assert isinstance(get_web_search("tavily"), TavilyWebSearch)
