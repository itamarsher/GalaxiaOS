"""Tavily web-search adapter — REAL web results (credential-gated).

Tavily is purpose-built for AI agents: it returns clean ``title``/``url``/
``content`` items, which map directly onto :class:`SearchResult`. The API key
comes from settings (``ABOS_TAVILY_API_KEY``); without it, :meth:`search`
raises :class:`WebSearchError` rather than hitting the network.

Off by default (``ABOS_WEB_SEARCH_PROVIDER=simulated``). Enable with
``ABOS_WEB_SEARCH_PROVIDER=tavily`` and a key. The HTTP shape is parsed by the
pure :meth:`_parse` staticmethod so result mapping is unit-testable offline.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.integrations.websearch import SearchResult, WebSearchError

_ENDPOINT = "https://api.tavily.com/search"


class TavilyWebSearch:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        search_depth: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.tavily_api_key
        self._search_depth = search_depth or settings.tavily_search_depth
        self._timeout = timeout if timeout is not None else settings.web_search_timeout_seconds

    def _require_key(self) -> str:
        if not self._api_key:
            raise WebSearchError(
                "Tavily API key missing (set ABOS_TAVILY_API_KEY)."
            )
        return self._api_key

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        key = self._require_key()
        payload = {
            "api_key": key,
            "query": query,
            "max_results": max(1, max_results),
            "search_depth": self._search_depth,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(_ENDPOINT, json=payload)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            raise WebSearchError(f"Tavily request failed: {exc}") from exc
        except ValueError as exc:  # non-JSON body
            raise WebSearchError(f"Tavily returned non-JSON: {exc}") from exc
        return self._parse(body)

    @staticmethod
    def _parse(body: dict) -> list[SearchResult]:
        """Map Tavily's ``{"results": [{title,url,content}, ...]}`` to results."""
        results: list[SearchResult] = []
        for item in body.get("results") or []:
            url = item.get("url") or ""
            results.append(
                SearchResult(
                    title=item.get("title") or url or "(untitled)",
                    url=url,
                    snippet=item.get("content") or "",
                )
            )
        return results
