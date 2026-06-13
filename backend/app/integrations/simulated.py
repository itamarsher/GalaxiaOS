"""Deterministic, network-free :class:`DomainRegistrar` for dev and tests.

Availability and price are derived purely from the TLD so the same domain always
yields the same quote, and registration is a no-op that "succeeds". This is the
default registrar so the agent loop and tests never touch the network or spend
real money.
"""

from __future__ import annotations

import uuid

from app.integrations import _pricing
from app.integrations.base import DomainQuote, DomainRegistration, RegistrarError


class SimulatedRegistrar:
    """In-memory registrar. Same input -> same quote, no network, no real spend."""

    async def check(self, domain: str) -> DomainQuote:
        if not _pricing.is_registrable(domain):
            return DomainQuote(domain=domain, available=False, price_cents=0)
        return DomainQuote(domain=domain, available=True, price_cents=_pricing.price_cents(domain))

    async def register(self, domain: str) -> DomainRegistration:
        if not _pricing.is_registrable(domain):
            raise RegistrarError(f"{domain} is not registrable")
        return DomainRegistration(
            domain=domain,
            price_cents=_pricing.price_cents(domain),
            external_ref=f"sim:{uuid.uuid4().hex[:12]}",
        )
