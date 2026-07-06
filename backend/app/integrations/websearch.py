"""Web search seam — the agents' window onto the outside world.

A small Protocol plus the real, credential-gated adapters that satisfy it. There is
deliberately NO simulated/offline provider: faking search results would feed agents
fabricated "facts" they then plan around. When no real provider is configured,
:func:`get_web_search` returns ``None`` and the ``web_search`` tool reports the
capability is unsupported (and the agent can request it). Swap in a real provider
via ``ABOS_WEB_SEARCH_PROVIDER`` (e.g. ``tavily``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


class WebSearchError(RuntimeError):
    """Raised when a real provider fails (missing creds, HTTP error, bad body)."""


@runtime_checkable
class WebSearch(Protocol):
    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        """Return up to ``max_results`` results for ``query``. No side effects."""
        ...


def get_web_search(name: str | None = None) -> WebSearch | None:
    """Return the configured web-search provider, or ``None`` if none is wired.

    There is no simulated fallback: an unconfigured environment returns ``None`` so
    the ``web_search`` tool reports the capability is unsupported instead of
    fabricating results.
    """
    from app.config import settings

    key = (name or settings.web_search_provider).strip().lower()
    if key in ("", "none", "simulated"):
        return None
    if key == "tavily":
        from app.integrations.tavily import TavilyWebSearch

        return TavilyWebSearch()
    raise ValueError(f"unknown web search provider: {key!r}")
