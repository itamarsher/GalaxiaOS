"""DNS seam — manage the zone and records that point a domain at a host.

A :class:`DnsProvider` creates/looks up the authoritative zone for a domain
(returning the nameservers the registrar must delegate to), reports when the zone
is active, and upserts records. As with the other seams there is no simulated
provider: callers report the capability is unsupported rather than faking DNS
changes.

DNS is bring-your-own-key: the runtime entry point is
:func:`app.services.integrations.resolve_dns_provider`, which builds a per-company
adapter only when that company has saved credentials. :func:`get_dns_provider` is a
plain name→adapter selector (``cloudflare`` by default; ``none`` → ``None``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Zone:
    """An authoritative DNS zone for a domain."""

    zone_id: str
    nameservers: list[str]  # delegate the registrar's NS to these
    status: str  # provider status, e.g. "pending" | "active"


class DnsError(RuntimeError):
    """Raised when a DNS operation fails (vendor error, no creds)."""


@runtime_checkable
class DnsProvider(Protocol):
    async def ensure_zone(self, domain: str) -> Zone:
        """Create or look up the zone for ``domain`` (idempotent)."""
        ...

    async def zone_status(self, zone_id: str) -> str:
        """Return the zone's current status (e.g. "active")."""
        ...

    async def upsert_record(
        self, *, zone_id: str, type: str, name: str, content: str, proxied: bool = True
    ) -> str:
        """Create or update a DNS record. Returns the record id."""
        ...


def get_dns_provider(name: str | None = None) -> DnsProvider | None:
    """Construct a DNS provider by name (no credentials; the resolver supplies those).

    ``cloudflare`` (the default) → a :class:`CloudflareDns`; ``none`` → ``None``;
    anything else raises ``ValueError`` so a typo fails loudly.
    """
    key = (name or "cloudflare").strip().lower()
    if key == "none":
        return None
    if key == "cloudflare":
        from app.integrations.cloudflare import CloudflareDns

        return CloudflareDns()
    raise ValueError(f"unknown dns provider: {key!r}")
