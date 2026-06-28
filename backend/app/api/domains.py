"""Domains space — founder-facing search → buy → auto-connect.

A thin HTTP layer over :mod:`app.services.domains`. ``capabilities`` lets the UI
guide the founder (is a registrar wired? a DNS provider + site to connect to?);
``search`` quotes availability; ``purchase`` buys (budget-metered) and associates
in one call; ``associate`` connects an already-owned domain to a site.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.deps import CompanyDep, DbDep
from app.integrations.dns import DnsError
from app.integrations.email import EmailError
from app.models import SiteDomain
from app.schemas import (
    DomainAssociateRequest,
    DomainCapabilitiesOut,
    DomainOut,
    DomainPurchaseRequest,
    DomainQuoteOut,
    EmailDnsRecordOut,
    EmailSetupOut,
    EmailSetupRequest,
)
from app.services import domains as domains_svc
from app.services import email_setup as email_setup_svc

router = APIRouter(prefix="/companies/{company_id}/domains", tags=["domains"])


def _out(sd: SiteDomain) -> DomainOut:
    return DomainOut(
        id=sd.id,
        domain=sd.domain,
        status=sd.status.value,
        site_id=sd.site_id,
        last_error=sd.last_error,
        created_at=sd.created_at,
    )


@router.get("/capabilities", response_model=DomainCapabilitiesOut)
async def capabilities(company: CompanyDep, db: DbDep):
    cap = await domains_svc.capabilities(db, company_id=company.id)
    return DomainCapabilitiesOut(
        registrar=cap.registrar, can_buy=cap.can_buy, can_connect=cap.can_connect
    )


@router.get("/search", response_model=list[DomainQuoteOut])
async def search(company: CompanyDep, db: DbDep, q: str = ""):
    try:
        quotes = await domains_svc.search(db, company_id=company.id, query=q)
    except domains_svc.DomainsError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return [
        DomainQuoteOut(domain=x.domain, available=x.available, price_cents=x.price_cents)
        for x in quotes
    ]


@router.get("", response_model=list[DomainOut])
async def list_domains(company: CompanyDep, db: DbDep):
    rows = await domains_svc.list_domains(db, company_id=company.id)
    return [_out(r) for r in rows]


@router.post("/purchase", response_model=DomainOut)
async def purchase(company: CompanyDep, db: DbDep, body: DomainPurchaseRequest):
    try:
        sd = await domains_svc.purchase(
            db, company_id=company.id, domain=body.domain, site_id=body.site_id
        )
    except domains_svc.DomainsError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _out(sd)


@router.post("/{domain_id}/associate", response_model=DomainOut)
async def associate(
    company: CompanyDep, db: DbDep, domain_id: uuid.UUID, body: DomainAssociateRequest
):
    try:
        sd = await domains_svc.associate(
            db, company_id=company.id, domain_id=domain_id, site_id=body.site_id
        )
    except domains_svc.DomainsError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _out(sd)


@router.post("/email-setup", response_model=EmailSetupOut)
async def email_setup(company: CompanyDep, db: DbDep, body: EmailSetupRequest):
    """Auto-configure sending email for ``domain``: register it with Resend, write
    the SPF/DKIM/DMARC records into Cloudflare, and trigger verification."""
    try:
        result = await email_setup_svc.configure_sender_dns(
            db, company_id=company.id, domain=body.domain
        )
    except (EmailError, DnsError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return EmailSetupOut(
        domain=result.domain,
        status=result.status,
        all_written=result.all_written,
        records=[
            EmailDnsRecordOut(record=r.record, type=r.type, name=r.name, ok=r.ok, error=r.error)
            for r in result.records
        ],
    )
