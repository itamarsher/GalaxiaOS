"""Automatic email-sending DNS setup: Resend records → the company's Cloudflare zone.

Cloudflare can't *send* mail (Email Routing is receive-only; Email Sending is a
paid, Workers-binding beta), so ABOS sends through Resend — and Resend's free tier
is the most generous of the options. The friction has always been the DNS:
SPF/DKIM/DMARC records the founder had to copy by hand. Since ABOS already manages
the company's Cloudflare DNS, we do it for them:

1. register/look up the sending domain with Resend (yields the required records),
2. ensure the Cloudflare zone exists, upsert each record (MX/TXT/CNAME) into it,
3. trigger Resend verification.

Both halves are bring-your-own-key (Resend key + Cloudflare creds, per company) and
degrade honestly: a missing key or DNS provider raises a clear error rather than
half-configuring. Records Resend returns are written verbatim; any that fail are
reported so the founder can finish a stray one rather than being told "all good".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.dns import DnsError
from app.integrations.email import EmailError
from app.integrations.resend_domains import ResendDomains, ResendRecord
from app.services import apikeys
from app.services.integrations import resolve_dns_provider

# Provider key the company's Resend secret is stored under (matches the send path).
_RESEND_KEY_PROVIDER = "resend"


@dataclass(frozen=True)
class RecordResult:
    record: str  # auth role (SPF/DKIM/DMARC)
    type: str
    name: str  # the FQDN actually written
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class EmailSetupResult:
    domain: str
    status: str  # Resend's domain status after verify was triggered
    records: list[RecordResult]

    @property
    def all_written(self) -> bool:
        return all(r.ok for r in self.records)


@dataclass(frozen=True)
class EmailStatusResult:
    domain: str
    configured: bool  # a Resend key is attached for this company
    status: str  # Resend domain status (or "not_configured"/"not_started"/"error")
    pending: list[str]  # record FQDNs Resend hasn't verified yet


def fqdn(name: str, domain: str) -> str:
    """Normalize a Resend record name to an absolute host under ``domain``.

    Resend returns names either relative (``send``, ``resend._domainkey``) or
    already absolute; Cloudflare wants the FQDN. ``@`` maps to the apex.
    """
    name = (name or "").strip().rstrip(".")
    domain = domain.strip().rstrip(".").lower()
    if name in ("", "@"):
        return domain
    if name.lower() == domain or name.lower().endswith("." + domain):
        return name
    return f"{name}.{domain}"


async def _write_record(dns, *, zone_id: str, domain: str, rec: ResendRecord) -> RecordResult:
    name = fqdn(rec.name, domain)
    try:
        await dns.upsert_record(
            zone_id=zone_id,
            type=rec.type,
            name=name,
            content=rec.value,
            proxied=False,  # email auth records are never proxied
            priority=rec.priority,
        )
        return RecordResult(record=rec.record, type=rec.type, name=name, ok=True)
    except DnsError as exc:
        return RecordResult(record=rec.record, type=rec.type, name=name, ok=False, error=str(exc))


async def configure_sender_dns(
    db: AsyncSession, *, company_id: uuid.UUID, domain: str
) -> EmailSetupResult:
    """Register ``domain`` with Resend, write its DNS into Cloudflare, and verify.

    Raises :class:`EmailError` if no Resend key is attached, or :class:`DnsError`
    if Cloudflare isn't connected — the two prerequisites for sending branded mail.
    """
    domain = domain.strip().lower().rstrip(".")
    key = await apikeys.get_plaintext_key(db, company_id=company_id, provider=_RESEND_KEY_PROVIDER)
    if not key:
        raise EmailError(
            "No Resend key attached for this company — add one in Settings to send branded email."
        )
    dns = await resolve_dns_provider(db, company_id=company_id)
    if dns is None:
        raise DnsError("Cloudflare isn't connected — connect it to auto-configure email DNS.")

    resend = ResendDomains(key)
    rd = await resend.create_or_get(domain)
    zone = await dns.ensure_zone(domain)

    results = [
        await _write_record(dns, zone_id=zone.zone_id, domain=domain, rec=r) for r in rd.records
    ]

    # Ask Resend to (re)check now that the records are in place. Best-effort: a
    # not-yet-propagated check shouldn't fail the whole setup.
    try:
        await resend.verify(rd.id)
    except EmailError:
        pass
    refreshed = await resend.get(rd.id)
    return EmailSetupResult(domain=domain, status=refreshed.status, records=results)


async def email_status(
    db: AsyncSession, *, company_id: uuid.UUID, domain: str
) -> EmailStatusResult:
    """Live Resend verification status for ``domain`` — cheap enough to poll.

    Never raises: a missing key reports ``not_configured``, an unregistered domain
    ``not_started``, and a transient Resend error ``error`` — so a polling client
    can render progress without handling exceptions every tick.
    """
    domain = domain.strip().lower().rstrip(".")
    key = await apikeys.get_plaintext_key(db, company_id=company_id, provider=_RESEND_KEY_PROVIDER)
    if not key:
        return EmailStatusResult(
            domain=domain, configured=False, status="not_configured", pending=[]
        )
    try:
        rd = await ResendDomains(key).find(domain)
    except EmailError:
        return EmailStatusResult(domain=domain, configured=True, status="error", pending=[])
    if rd is None:
        return EmailStatusResult(domain=domain, configured=True, status="not_started", pending=[])
    pending = [fqdn(r.name, domain) for r in rd.records if r.status != "verified"]
    return EmailStatusResult(domain=domain, configured=True, status=rd.status, pending=pending)
