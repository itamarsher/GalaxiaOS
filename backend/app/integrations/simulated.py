"""Deterministic, network-free :class:`DomainRegistrar` for dev and tests.

Pricing is derived purely from the TLD so the same domain always yields the
same quote. ``.test`` / ``.invalid`` (and other reserved TLDs) are reported
unavailable so callers can exercise the "not available, do not charge" path.
"""

from __future__ import annotations

from app.integrations.base import DomainQuote

# Reserved/special-use TLDs we always report as unavailable (RFC 2606 + friends).
_UNAVAILABLE_TLDS = frozenset({"test", "invalid", "example", "localhost"})

# TLDs that price as "premium". Everything else falls back to the common price.
_PREMIUM_TLDS = frozenset({"ai", "io", "dev", "app", "co"})

_COMMON_PRICE_CENTS = 1200  # ~$12 — .com/.net/.org and the long tail.
_PREMIUM_PRICE_CENTS = 4000  # ~$40 — sought-after TLDs.


def _tld(domain: str) -> str:
    return domain.rsplit(".", 1)[-1].strip().lower()


class SimulatedRegistrar:
    """In-memory registrar. Same input -> same quote, no network."""

    async def check(self, domain: str) -> DomainQuote:
        normalized = domain.strip().lower()
        tld = _tld(normalized)

        if not normalized or "." not in normalized or tld in _UNAVAILABLE_TLDS:
            return DomainQuote(domain=domain, available=False, price_cents=0)

        price = _PREMIUM_PRICE_CENTS if tld in _PREMIUM_TLDS else _COMMON_PRICE_CENTS
        return DomainQuote(domain=domain, available=True, price_cents=price)
