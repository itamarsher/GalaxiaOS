"""Domain registrar seam.

A :class:`DomainRegistrar` answers "is this domain available and what does it
cost?" without committing any spend. Charging stays the runtime's job and flows
through :class:`~app.runtime.cost_meter.CostMeter`; the registrar only quotes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class DomainQuote:
    """The result of checking a domain: availability and price (in cents)."""

    domain: str
    available: bool
    price_cents: int


@runtime_checkable
class DomainRegistrar(Protocol):
    """Quotes domain availability and price. Implementations must not spend."""

    async def check(self, domain: str) -> DomainQuote:
        """Return a :class:`DomainQuote` for ``domain``. No side effects."""
        ...
