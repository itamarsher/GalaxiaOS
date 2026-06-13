"""Domain registrar seam.

A :class:`DomainRegistrar` answers "is this domain available and what does it
cost?" (:meth:`check`) and performs the actual registration (:meth:`register`).

Money is never moved by the registrar itself — the runtime wraps
:meth:`register` in :meth:`~app.runtime.cost_meter.CostMeter.metered_external`,
which reserves the budget *before* the (irreversible) registration call and
commits the actual charge after. The registrar returns the price and an opaque
vendor reference; it does not touch ``budgets``.
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


@dataclass(frozen=True)
class DomainRegistration:
    """The result of a successful registration."""

    domain: str
    price_cents: int
    external_ref: str  # opaque vendor order/reference id


class RegistrarError(RuntimeError):
    """Raised when a registration fails (unavailable, vendor error, no creds)."""


@runtime_checkable
class DomainRegistrar(Protocol):
    async def check(self, domain: str) -> DomainQuote:
        """Return a :class:`DomainQuote` for ``domain``. No side effects."""
        ...

    async def register(self, domain: str) -> DomainRegistration:
        """Register ``domain`` with the vendor. Raises :class:`RegistrarError`
        on failure. Must NOT touch the budget — the caller meters the charge."""
        ...
