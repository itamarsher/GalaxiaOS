"""Tavily adapter — REAL web results (credential-gated), for both search and fetch.

Tavily is purpose-built for AI agents. :meth:`search` returns clean ``title``/
``url``/``content`` items mapped onto :class:`SearchResult` (powers ``web_search``);
:meth:`extract` returns the full page body of given URLs mapped onto
:class:`FetchResult` (powers ``web_fetch``). Both share one API key (from settings,
``ABOS_TAVILY_API_KEY``, or a per-company key); without it they raise
:class:`WebSearchError` rather than hitting the network.

Off by default (``ABOS_WEB_SEARCH_PROVIDER=simulated``). Enable with
``ABOS_WEB_SEARCH_PROVIDER=tavily`` and a key. The HTTP shapes are parsed by the
pure :meth:`_parse` / :meth:`_parse_extract` staticmethods so result mapping is
unit-testable offline.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.integrations.websearch import FetchResult, SearchResult, WebSearchError

_ENDPOINT = "https://api.tavily.com/search"
_EXTRACT_ENDPOINT = "https://api.tavily.com/extract"


class TavilyWebSearch:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        search_depth: str | None = None,
        extract_depth: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.tavily_api_key
        self._search_depth = search_depth or settings.tavily_search_depth
        self._extract_depth = extract_depth or settings.tavily_extract_depth
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
            raise WebSearchError("Tavily API key missing (set ABOS_TAVILY_API_KEY).")
        return self._api_key

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        """Raise :class:`WebSearchError` with Tavily's own error detail on failure.

        ``resp.raise_for_status()`` alone only ever produces a generic "Client
        error '432 Client Error' for url '...'" message — it never reads the
        response body, which is where Tavily puts the actual reason. We read the
        body first (even on non-2xx) and fold any ``detail``/``error`` field into
        the message. HTTP 432 is Tavily's non-standard "plan/usage limit
        exceeded" code, so that case gets an actionable hint to self-configure a
        key instead of a bare status line.
        """
        if resp.status_code < 400:
            return
        detail = None
        try:
            body = resp.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            detail = body.get("detail") or body.get("error")
            if isinstance(detail, dict):
                detail = detail.get("error") or detail.get("message")
        if resp.status_code == 432:
            message = (
                "Tavily usage limit exceeded (HTTP 432)"
                + (f": {detail}" if detail else "")
                + " — self-configure your own Tavily key with `configure_integration` "
                "if you need web search to keep working."
            )
            raise WebSearchError(message)
        if detail:
            raise WebSearchError(f"Tavily request failed: HTTP {resp.status_code}: {detail}")
        try:
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise WebSearchError(f"Tavily request failed: {exc}") from exc

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
                self._raise_for_status(resp)
                body = resp.json()
        except httpx.HTTPError as exc:
            raise WebSearchError(f"Tavily request failed: {exc}") from exc
        except ValueError as exc:  # non-JSON body
            raise WebSearchError(f"Tavily returned non-JSON: {exc}") from exc
        self.last_usage_credits = self._usage_credits(body)
        self.last_request_id = body.get("request_id")
        return self._parse(body)

    async def extract(self, urls: list[str]) -> list[FetchResult]:
        """Extract the main text of each URL via Tavily's ``/extract`` endpoint.

        Returns one :class:`FetchResult` per input URL — a successful extraction
        carries the page's clean ``content``; a URL Tavily could not retrieve comes
        back with ``error`` set and empty content (so a partial batch is honest
        about what worked). Billing telemetry (``last_usage_credits`` /
        ``last_request_id``) is populated exactly as :meth:`search` does, so the
        CostMeter reconciles the real credit spend the same way.
        """
        key = self._require_key()
        payload = {
            "api_key": key,
            "urls": urls,
            "extract_depth": self._extract_depth,
            "include_usage": True,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(_EXTRACT_ENDPOINT, json=payload)
                self._raise_for_status(resp)
                body = resp.json()
        except httpx.HTTPError as exc:
            raise WebSearchError(f"Tavily extract failed: {exc}") from exc
        except ValueError as exc:  # non-JSON body
            raise WebSearchError(f"Tavily returned non-JSON: {exc}") from exc
        self.last_usage_credits = self._usage_credits(body)
        self.last_request_id = body.get("request_id")
        return self._parse_extract(body)

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
    def _parse_extract(body: dict) -> list[FetchResult]:
        """Map Tavily's extract body to :class:`FetchResult`.

        Success items live under ``results`` (``{url, raw_content}``); URLs Tavily
        could not fetch live under ``failed_results`` (``{url, error}``) and are
        surfaced as results carrying the error so the caller can report them.
        """
        results: list[FetchResult] = []
        for item in body.get("results") or []:
            results.append(
                FetchResult(
                    url=item.get("url") or "",
                    content=item.get("raw_content") or "",
                )
            )
        for item in body.get("failed_results") or []:
            results.append(
                FetchResult(
                    url=item.get("url") or "",
                    content="",
                    error=str(item.get("error") or "could not fetch"),
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


async def verify_credentials(api_key: str) -> None:
    """Confirm a Tavily key works, raising :class:`WebSearchError` if not.

    Used when an agent self-configures Tavily via ``configure_integration`` so a
    bad key is rejected up front and never stored — the same honest verify-before-
    store guard the Cloudflare flow uses. Runs the cheapest possible real call (a
    single-result search), which raises on an auth/HTTP failure.
    """
    if not (api_key or "").strip():
        raise WebSearchError("Tavily API key missing.")
    await TavilyWebSearch(api_key=api_key).search("connectivity check", max_results=1)
