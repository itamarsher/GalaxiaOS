"""Offline unit tests for the Tavily web-search adapter (no network)."""

from __future__ import annotations

import pytest

from app.integrations.tavily import TavilyWebSearch
from app.integrations.websearch import (
    FetchResult,
    SearchResult,
    WebSearchError,
    get_web_search,
)


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


# ── web_fetch / extract ──────────────────────────────────────────────────────────
def test_parse_extract_maps_raw_content():
    body = {
        "results": [
            {"url": "https://foo.test", "raw_content": "the full text of foo"},
            {"url": "https://bar.test", "raw_content": "the full text of bar"},
        ]
    }
    assert TavilyWebSearch._parse_extract(body) == [
        FetchResult(url="https://foo.test", content="the full text of foo"),
        FetchResult(url="https://bar.test", content="the full text of bar"),
    ]


def test_parse_extract_surfaces_failed_urls():
    body = {
        "results": [{"url": "https://ok.test", "raw_content": "hello"}],
        "failed_results": [{"url": "https://bad.test", "error": "timeout"}],
    }
    results = TavilyWebSearch._parse_extract(body)
    assert FetchResult(url="https://ok.test", content="hello") in results
    [failed] = [r for r in results if r.error]
    assert failed.url == "https://bad.test" and failed.error == "timeout"


def test_parse_extract_tolerates_empty():
    assert TavilyWebSearch._parse_extract({}) == []


@pytest.mark.asyncio
async def test_extract_missing_key_raises_without_network():
    client = TavilyWebSearch(api_key="")
    with pytest.raises(WebSearchError):
        await client.extract(["https://x.test"])


@pytest.mark.asyncio
async def test_verify_credentials_rejects_empty_key_without_network():
    from app.integrations.tavily import verify_credentials

    with pytest.raises(WebSearchError):
        await verify_credentials("")
