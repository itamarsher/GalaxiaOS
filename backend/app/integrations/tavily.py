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
        # Per-call billing telemetry from the most recent :meth:`search`. Tavily
        # reports consumption in *API credits* (basic=1, advanced=2), not dollars,
        # so the CostMeter reconciles the actual charge as
        # ``credits × web_search_cost_cents``. ``None`` until a real search runs
        # (or if the provider omits the ``usage`` block). A fresh adapter is built
        # per call (see ``_resolve_web_search``), so this is not shared state.
        self.last_usage_credits: int | None = None
        self.last_request_id: str | None = None

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
            # Ask Tavily to report the credits this exact request consumed so the
            # meter charges measured usage rather than a depth-based assumption.
            "include_usage": True,
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
        self.last_usage_credits = self._usage_credits(body)
        self.last_request_id = body.get("request_id")
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

    @staticmethod
    def _usage_credits(body: dict) -> int | None:
        """Extract ``usage.credits`` (API credits consumed) from a Tavily body.

        Present only when the request set ``include_usage``; returns ``None`` if
        the block is absent or malformed so callers can fall back to the
        depth-based estimate rather than mis-charging.
        """
        usage = body.get("usage")
        if not isinstance(usage, dict):
            return None
        credits = usage.get("credits")
        return credits if isinstance(credits, int) else None
