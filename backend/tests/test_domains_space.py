"""Domains space: capabilities, search, and the buy → auto-associate flow."""

from __future__ import annotations

import pytest

from app.integrations.base import DomainQuote, DomainRegistration
from app.models import Site, SiteDomain
from app.models.enums import SiteConnectStatus, SiteStatus
from app.runtime.cost_meter import CostMeter
from app.services import budget as budget_svc
from app.services import domains as domains_svc
from tests.conftest import requires_db


class _StubRegistrar:
    def __init__(self, *, available: bool = True, price: int = 1200):
        self._available, self._price = available, price

    async def check(self, domain: str) -> DomainQuote:
        return DomainQuote(domain=domain, available=self._available, price_cents=self._price)

    async def register(self, domain: str) -> DomainRegistration:
        return DomainRegistration(domain=domain, price_cents=self._price, external_ref="ext-1")

    async def set_nameservers(self, domain, nameservers):  # pragma: no cover
        return None


# ── search (pure) ─────────────────────────────────────────────────────────────


async def test_search_requires_a_registrar(monkeypatch):
    monkeypatch.setattr(domains_svc, "get_registrar", lambda: None)
    with pytest.raises(domains_svc.DomainsError):
        await domains_svc.search(None, company_id=None, query="acme")


async def test_search_expands_bare_name_across_tlds(monkeypatch):
    monkeypatch.setattr(domains_svc, "get_registrar", lambda: _StubRegistrar())
    quotes = await domains_svc.search(None, company_id=None, query="Acme")
    assert [q.domain for q in quotes] == ["acme.com", "acme.ai", "acme.io", "acme.co"]
    # An explicit FQDN is quoted as-is.
    one = await domains_svc.search(None, company_id=None, query="acme.dev")
    assert [q.domain for q in one] == ["acme.dev"]


# ── capabilities + purchase + associate (DB) ──────────────────────────────────


@requires_db
async def test_capabilities_default_is_honest(session_factory, company_with_budget):
    # Default config: simulated registrar (no buy), no DNS/site (no connect).
    async with session_factory() as db:
        cap = await domains_svc.capabilities(db, company_id=company_with_budget)
    assert cap.registrar == "simulated"
    assert cap.can_buy is False
    assert cap.can_connect is False


@requires_db
async def test_purchase_buys_metered_and_records_unconnected(
    session_factory, company_with_budget, monkeypatch
):
    monkeypatch.setattr(domains_svc, "get_registrar", lambda: _StubRegistrar(price=1200))
    async with session_factory() as db:
        sd = await domains_svc.purchase(
            db,
            company_id=company_with_budget,
            domain="Acme.com",
            meter=CostMeter(session_factory),  # the metered charge hits the test DB
        )
        assert sd.domain == "acme.com"
        assert sd.site_id is None  # no published site -> bought but unconnected
        assert sd.status == SiteConnectStatus.pending_ns

    # The purchase was charged through the budget (reserve -> commit).
    async with session_factory() as db:
        budget = await budget_svc.get_active_budget(db, company_with_budget)
        assert budget.spent_cents == 1200
        by_cat = await budget_svc.spend_by_category(db, company_with_budget)
        assert by_cat["external"] == 1200
        # Exactly one owned-domain row.
        owned = await domains_svc.list_domains(db, company_id=company_with_budget)
        assert [d.domain for d in owned] == ["acme.com"]


@requires_db
async def test_purchase_auto_kicks_email_setup_best_effort(
    session_factory, company_with_budget, monkeypatch
):
    monkeypatch.setattr(domains_svc, "get_registrar", lambda: _StubRegistrar())
    called = {}

    async def _fake_setup(db, *, company_id, domain):
        called["domain"] = domain
        # Even if email setup blows up, the purchase must still succeed.
        raise domains_svc.EmailError("no key")

    monkeypatch.setattr(domains_svc.email_setup_svc, "configure_sender_dns", _fake_setup)
    async with session_factory() as db:
        sd = await domains_svc.purchase(
            db,
            company_id=company_with_budget,
            domain="acme.com",
            meter=CostMeter(session_factory),
        )
    assert sd.domain == "acme.com"  # purchase succeeded despite email setup failing
    assert called["domain"] == "acme.com"  # …and email setup was auto-attempted


@requires_db
async def test_purchase_refuses_unavailable_domain(
    session_factory, company_with_budget, monkeypatch
):
    monkeypatch.setattr(domains_svc, "get_registrar", lambda: _StubRegistrar(available=False))
    async with session_factory() as db:
        with pytest.raises(domains_svc.DomainsError, match="not available"):
            await domains_svc.purchase(
                db,
                company_id=company_with_budget,
                domain="taken.com",
                meter=CostMeter(session_factory),
            )
    # Nothing charged, nothing recorded.
    async with session_factory() as db:
        budget = await budget_svc.get_active_budget(db, company_with_budget)
        assert budget.spent_cents == 0
        assert await domains_svc.list_domains(db, company_id=company_with_budget) == []


@requires_db
async def test_associate_points_domain_at_site_and_degrades_without_dns(
    session_factory, company_with_budget
):
    async with session_factory() as db:
        site = Site(
            company_id=company_with_budget,
            slug="launch",
            title="Launch",
            status=SiteStatus.published,
            project_name="abos-launch",
        )
        db.add(site)
        sd = SiteDomain(
            company_id=company_with_budget,
            domain="acme.com",
            status=SiteConnectStatus.pending_ns,
        )
        db.add(sd)
        await db.commit()
        site_id, domain_id = site.id, sd.id

    async with session_factory() as db:
        out = await domains_svc.associate(
            db, company_id=company_with_budget, domain_id=domain_id, site_id=site_id
        )
        assert out.site_id == site_id
        # No Cloudflare key wired -> connection can't start; recorded, not raised.
        assert out.last_error and "DNS provider" in out.last_error
