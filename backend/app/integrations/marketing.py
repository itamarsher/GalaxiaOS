"""Marketing publishing seam — how agents publish content.

Mirrors the other integration seams (``email``, ``websearch``): a Protocol plus
a ``simulated`` default that is deterministic and network-free, so the agent loop
and tests never hit a real CMS/social API. The simulated publisher derives a
stable slug + URL from the channel and title — same inputs always produce the
same URL — and performs no I/O.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

#: Base host used for deterministic simulated published URLs.
_BASE_URL = "https://content.simulated.local"

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    """Deterministic, URL-safe slug for a title (network-free, stable)."""
    slug = _SLUG_STRIP.sub("-", title.strip().lower()).strip("-")
    if not slug:
        # Fall back to a stable hash so empty/symbol-only titles still slug.
        slug = hashlib.sha256(title.encode()).hexdigest()[:12]
    return slug[:80]


def published_url(channel: str, title: str) -> str:
    """Derive a deterministic published URL from channel + title (no network)."""
    return f"{_BASE_URL}/{channel}/{slugify(title)}"


@dataclass(frozen=True)
class PublishResult:
    url: str
    provider: str


@runtime_checkable
class Publisher(Protocol):
    async def publish(self, *, channel: str, title: str, body: str) -> PublishResult:
        """Publish content and return its URL."""
        ...


class SimulatedPublisher:
    """Deterministic, offline publisher. Same inputs -> same URL; no network."""

    async def publish(self, *, channel: str, title: str, body: str) -> PublishResult:
        return PublishResult(url=published_url(channel, title), provider="simulated")


def get_publisher(name: str | None = None) -> Publisher:
    """Return the configured publisher (defaults to simulated)."""
    key = (name or "simulated").strip().lower()
    if key in ("", "none", "simulated"):
        return SimulatedPublisher()
    raise ValueError(f"unknown publisher: {key!r}")
