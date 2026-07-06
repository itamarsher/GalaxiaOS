"""RDAP-backed registrar: real availability, simulated purchase.

``check`` uses live RDAP (no credentials) for genuine availability; price comes
from the shared TLD table. ``register`` does NOT actually buy a domain (RDAP is
read-only) — it returns a simulated registration so the metered purchase path is
exercised end to end without a paid vendor. Use ``namecheap`` for real purchase.
"""

from __future__ import annotations

import uuid

from app.config import settings
from app.integrations import _pricing
from app.integrations.availability import rdap_available
from app.integrations.base import DomainQuote, DomainRegistration, RegistrarError


class RdapRegistrar:
    async def check(self, domain: str) -> DomainQuote:
        if not _pricing.is_registrable(domain):
            return DomainQuote(domain=domain, available=False, price_cents=0)
        available = await rdap_available(domain, timeout=settings.rdap_timeout_seconds)
        # Unknown (network failure) -> treat as unavailable so we never charge on a guess.
        if available is not True:
            return DomainQuote(domain=domain, available=False, price_cents=0)
        return DomainQuote(domain=domain, available=True, price_cents=_pricing.price_cents(domain))

    async def register(self, domain: str) -> DomainRegistration:
        quote = await self.check(domain)
        if not quote.available:
            raise RegistrarError(f"{domain} is not available")
        return DomainRegistration(
            domain=domain,
            price_cents=quote.price_cents,
            external_ref=f"rdap-sim:{uuid.uuid4().hex[:12]}",
        )
