"""DNS seam — manage the zone and records that point a domain at a host.

A :class:`DnsProvider` creates/looks up the authoritative zone for a domain
(returning the nameservers the registrar must delegate to), reports when the zone
is active, and upserts records. As with the other seams there is no simulated
provider: :func:`get_dns_provider` returns ``None`` when unconfigured and callers
report the capability is unsupported rather than faking DNS changes.

Selection is driven by ``settings.dns_provider`` (env ``ABOS_DNS_PROVIDER``):

- ``none`` (default) — :func:`get_dns_provider` returns ``None``.
- ``cloudflare`` — Cloudflare DNS, credential-gated.
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
    """Return the configured DNS provider, or ``None`` if none is wired.

    ``name`` overrides ``settings.dns_provider`` when given. Unknown names raise
    ``ValueError`` so a misconfiguration fails loudly.
    """
    from app.config import settings

    key = (name or settings.dns_provider).strip().lower()
    if key == "none":
        return None
    if key == "cloudflare":
        from app.integrations.cloudflare import CloudflareDns

        return CloudflareDns()
    raise ValueError(f"unknown dns provider: {key!r}")
