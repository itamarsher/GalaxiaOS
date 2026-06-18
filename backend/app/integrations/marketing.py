"""Marketing publishing seam — how agents publish content.

A Protocol describing the shape a real CMS/social adapter would satisfy. There is
deliberately NO simulated publisher: fabricating a "published" URL lets agents
believe content went live when it did not. Until a real adapter is wired,
:func:`get_publisher` returns ``None`` and the ``publish_content`` tool reports the
capability is unsupported (the agent can request it).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PublishResult:
    url: str
    provider: str


@runtime_checkable
class Publisher(Protocol):
    async def publish(self, *, channel: str, title: str, body: str) -> PublishResult:
        """Publish content and return its URL."""
        ...


def get_publisher(name: str | None = None) -> Publisher | None:
    """Return the configured publisher, or ``None`` if none is wired (the default)."""
    return None
