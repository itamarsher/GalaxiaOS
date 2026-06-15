"""Web search seam — the agents' window onto the outside world.

Mirrors the domain-registrar seam (:mod:`app.integrations.base`): a Protocol
plus a ``simulated`` default that is deterministic and network-free, so the
agent loop and tests never touch the network. Swap in a real provider behind
the same interface via ``ABOS_WEB_SEARCH_PROVIDER`` (real adapters are
credential-gated, like the namecheap registrar).
"""

from __future__ import annotations

import hashlib
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


class SimulatedWebSearch:
    """Deterministic, offline web search. Same query -> same results."""

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        seed = hashlib.sha256(query.encode()).hexdigest()
        results: list[SearchResult] = []
        for i in range(max(0, max_results)):
            tag = seed[i * 4 : i * 4 + 4] or "0000"
            results.append(
                SearchResult(
                    title=f"[simulated] {query} — result {i + 1}",
                    url=f"https://example.com/{tag}",
                    snippet=(
                        f"Simulated search result {i + 1} for {query!r}. "
                        "Set ABOS_WEB_SEARCH_PROVIDER to a live adapter for real results."
                    ),
                )
            )
        return results


def get_web_search(name: str | None = None) -> WebSearch:
    """Return the configured web-search provider (defaults to simulated)."""
    from app.config import settings

    key = (name or settings.web_search_provider).strip().lower()
    if key in ("", "none", "simulated"):
        return SimulatedWebSearch()
    if key == "tavily":
        from app.integrations.tavily import TavilyWebSearch

        return TavilyWebSearch()
    raise ValueError(f"unknown web search provider: {key!r}")
