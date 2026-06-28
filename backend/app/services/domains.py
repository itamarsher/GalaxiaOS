"""Domains space: search availability, buy a domain, auto-associate it to a site.

A founder-facing wrapper that ties the registrar seam (buy) and the sites
connection state machine (associate) into one minimal-involvement flow:
search → "buy & connect". The growth agent's ``register_domain`` tool buys
autonomously; this exposes the same machinery to the founder.

Money still flows through :class:`~app.runtime.cost_meter.CostMeter` (the budget is
reserved before the irreversible registration), and association reuses
:mod:`app.services.sites` (Cloudflare DNS). Both halves degrade honestly: with no
registrar configured, buying reports unsupported; with no DNS/site wired, the
domain is still bought and recorded — just left unconnected for later.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.integrations.base import DomainQuote, RegistrarError
from app.integrations.dns import DnsError
from app.integrations.email import EmailError
from app.integrations.registry import get_registrar
from app.models import Site, SiteDomain
from app.models.enums import SiteConnectStatus
from app.runtime.cost_meter import CostMeter
from app.services import apikeys
from app.services import email_setup as email_setup_svc
from app.services import sites as sites_svc

# Provider key a company's Resend secret is stored under (matches the send path).
_RESEND_KEY_PROVIDER = "resend"

# When the founder types a bare name (no dot), quote it across a few common TLDs.
_SUGGEST_TLDS = ("com", "ai", "io", "co")


class DomainsError(RuntimeError):
    """A domains action couldn't proceed (no registrar, unavailable, vendor error)."""


@dataclass(frozen=True)
class Capabilities:
    registrar: str  # the configured registrar name (e.g. "simulated", "namecheap")
    can_buy: bool  # a real registrar is wired (else search/purchase report unsupported)
    can_connect: bool  # a DNS provider *and* a site exist to point a bought domain at
    can_send_email: bool  # a Resend key is attached, so email auto-setup can run


async def capabilities(db: AsyncSession, *, company_id: uuid.UUID) -> Capabilities:
    """What the Domains space can do right now, so the UI can guide the founder."""
    dns = await sites_svc.resolve_dns_provider(db, company_id=company_id)
    site = await sites_svc.latest_published_site(db, company_id=company_id)
    has_resend = await apikeys.has_active_key(
        db, company_id=company_id, provider=_RESEND_KEY_PROVIDER
    )
    return Capabilities(
        registrar=settings.domain_registrar,
        can_buy=get_registrar() is not None,
        can_connect=dns is not None and site is not None,
        can_send_email=has_resend,
    )


async def search(db: AsyncSession, *, company_id: uuid.UUID, query: str) -> list[DomainQuote]:
    """Availability + price for ``query`` (or a few TLD variants of a bare name)."""
    registrar = get_registrar()
    if registrar is None:
        raise DomainsError("No domain registrar is configured (set ABOS_DOMAIN_REGISTRAR).")
    q = query.strip().lower()
    if not q:
        return []
    candidates = [q] if "." in q else [f"{q}.{tld}" for tld in _SUGGEST_TLDS]
    quotes: list[DomainQuote] = []
    for domain in candidates:
        try:
            quotes.append(await registrar.check(domain))
        except RegistrarError:
            continue  # one variant failing shouldn't sink the whole search
    return quotes


async def list_domains(db: AsyncSession, *, company_id: uuid.UUID) -> list[SiteDomain]:
    """Every domain this company owns/owns-in-progress, newest first."""
    rows = await db.scalars(
        select(SiteDomain)
        .where(SiteDomain.company_id == company_id)
        .order_by(SiteDomain.created_at.desc())
    )
    return list(rows)


async def _record_domain(
    db: AsyncSession, *, company_id: uuid.UUID, domain: str, site: Site | None
) -> SiteDomain:
    """Upsert the owned-domain row, attaching it to ``site`` when one is given."""
    row = await db.scalar(
        select(SiteDomain).where(SiteDomain.company_id == company_id, SiteDomain.domain == domain)
    )
    if row is None:
        row = SiteDomain(
            company_id=company_id,
            site_id=site.id if site else None,
            domain=domain,
            status=SiteConnectStatus.pending_ns,
        )
        db.add(row)
        await db.flush()
    elif site is not None and row.site_id != site.id:
        row.site_id = site.id
        await db.flush()
    return row


async def _connect(db: AsyncSession, sd: SiteDomain) -> SiteDomain:
    """Drive the connection as far as providers allow; record (don't raise) errors."""
    try:
        return await sites_svc.begin_connection(db, sd=sd)
    except DnsError as exc:
        # No DNS provider / zone failure — the domain is bought, just unconnected.
        sd.last_error = str(exc)
        await db.flush()
        return sd


async def purchase(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    domain: str,
    site_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    meter: CostMeter | None = None,
) -> SiteDomain:
    """Buy ``domain`` (budget-metered) and auto-associate it to a site.

    Picks the target site explicitly (``site_id``) or falls back to the latest
    published one, so a typical purchase needs no further input. Raises
    :class:`DomainsError` when no registrar is wired, the domain is unavailable, or
    the vendor fails; ``BudgetExceeded`` propagates (the API maps it to 402).
    """
    domain = domain.strip().lower()
    registrar = get_registrar()
    if registrar is None:
        raise DomainsError("No domain registrar is configured (set ABOS_DOMAIN_REGISTRAR).")
    quote = await registrar.check(domain)
    if not quote.available:
        raise DomainsError(f"{domain} is not available to register.")

    async def _do_register() -> tuple[int, str | None, dict | None]:
        reg = await registrar.register(domain)
        return reg.price_cents, reg.external_ref, {"domain": domain}

    meter = meter or CostMeter(SessionLocal)
    try:
        await meter.metered_external(
            company_id=company_id,
            agent_id=agent_id,
            task_id=None,
            estimated_cents=quote.price_cents,
            vendor=f"registrar({settings.domain_registrar})",
            sku=domain,
            action=_do_register,
            description=f"domain {domain}",
        )
    except RegistrarError as exc:
        raise DomainsError(f"registration failed: {exc}") from exc

    site: Site | None = None
    if site_id is not None:
        site = await db.get(Site, site_id)
        if site is not None and site.company_id != company_id:
            site = None
    if site is None:
        site = await sites_svc.latest_published_site(db, company_id=company_id)

    sd = await _record_domain(db, company_id=company_id, domain=domain, site=site)
    if site is not None:
        sd = await _connect(db, sd)
    await db.commit()

    await _maybe_setup_email(db, company_id=company_id, domain=domain)
    return sd


async def _maybe_setup_email(db: AsyncSession, *, company_id: uuid.UUID, domain: str) -> None:
    """Best-effort: once a domain is bought, auto-configure sending email for it.

    Runs only when both prerequisites are in place (a Resend key and Cloudflare) —
    :func:`email_setup_svc.configure_sender_dns` raises otherwise, which we swallow
    so a missing prerequisite never fails the purchase. The founder can still run it
    by hand from the Domains space, and the status endpoint reports progress.
    """
    try:
        await email_setup_svc.configure_sender_dns(db, company_id=company_id, domain=domain)
    except (EmailError, DnsError):
        pass


async def associate(
    db: AsyncSession, *, company_id: uuid.UUID, domain_id: uuid.UUID, site_id: uuid.UUID
) -> SiteDomain:
    """Point an already-owned domain at a site and start the connection."""
    sd = await db.get(SiteDomain, domain_id)
    if sd is None or sd.company_id != company_id:
        raise DomainsError("domain not found")
    site = await db.get(Site, site_id)
    if site is None or site.company_id != company_id:
        raise DomainsError("site not found")
    sd.site_id = site.id
    await db.flush()
    sd = await _connect(db, sd)
    await db.commit()
    return sd
