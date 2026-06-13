"""Domain integration tests: RDAP mapping, registrars, and metered purchase."""

from __future__ import annotations

import pytest

from app.integrations.availability import interpret_status
from app.integrations.base import RegistrarError
from app.integrations.rdap import RdapRegistrar
from app.integrations.registry import get_registrar
from app.integrations.simulated import SimulatedRegistrar
from app.runtime.cost_meter import CostMeter
from app.services import budget as budget_svc
from app.services.budget import BudgetExceeded
from tests.conftest import requires_db

# ── pure ──────────────────────────────────────────────────────────────────────


def test_rdap_status_mapping():
    assert interpret_status(404) is True  # available
    assert interpret_status(200) is False  # taken
    assert interpret_status(429) is None  # unknown
    assert interpret_status(503) is None


async def test_simulated_registrar_check_and_register():
    reg = SimulatedRegistrar()
    q = await reg.check("acme.com")
    assert q.available and q.price_cents == 1200
    assert (await reg.check("foo.test")).available is False  # reserved TLD
    r = await reg.register("acme.io")
    assert r.price_cents == 4000 and r.external_ref.startswith("sim:")
    with pytest.raises(RegistrarError):
        await reg.register("nope.test")


async def test_rdap_registrar_unknown_availability_is_not_available(monkeypatch):
    # Simulate RDAP network failure (returns None) -> must NOT be available.
    async def fake_rdap(domain, *, timeout=4.0):
        return None

    monkeypatch.setattr("app.integrations.rdap.rdap_available", fake_rdap)
    q = await RdapRegistrar().check("anything.com")
    assert q.available is False
    with pytest.raises(RegistrarError):
        await RdapRegistrar().register("anything.com")


def test_registry_wiring():
    assert isinstance(get_registrar("simulated"), SimulatedRegistrar)
    assert isinstance(get_registrar("rdap"), RdapRegistrar)
    # namecheap resolves (adapter constructed) but registering without creds raises.
    get_registrar("namecheap")
    with pytest.raises(ValueError):
        get_registrar("bogus")


async def test_namecheap_register_without_credentials_raises():
    reg = get_registrar("namecheap")
    with pytest.raises(RegistrarError):
        await reg.register("acme.com")


# ── metered purchase path (DB) ────────────────────────────────────────────────


@requires_db
async def test_metered_external_reserves_then_commits(session_factory, company_with_budget):
    company_id = company_with_budget  # 10_000c limit
    meter = CostMeter(session_factory)

    async def action():
        return 1200, "ref-123", {"domain": "acme.com"}

    ref = await meter.metered_external(
        company_id=company_id,
        agent_id=None,
        task_id=None,
        estimated_cents=1200,
        vendor="registrar(test)",
        sku="acme.com",
        action=action,
    )
    assert ref == "ref-123"
    async with session_factory() as db:
        budget = await budget_svc.get_active_budget(db, company_id)
        assert budget.spent_cents == 1200
        assert budget.reserved_cents == 0
        by_cat = await budget_svc.spend_by_category(db, company_id)
    assert by_cat["external"] == 1200


@requires_db
async def test_metered_external_action_failure_releases_reservation(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    meter = CostMeter(session_factory)

    async def failing_action():
        raise RegistrarError("vendor said no")

    with pytest.raises(RegistrarError):
        await meter.metered_external(
            company_id=company_id,
            agent_id=None,
            task_id=None,
            estimated_cents=1200,
            vendor="registrar(test)",
            sku="acme.com",
            action=failing_action,
        )
    async with session_factory() as db:
        budget = await budget_svc.get_active_budget(db, company_id)
        assert budget.spent_cents == 0
        assert budget.reserved_cents == 0  # reservation released, nothing charged


@requires_db
async def test_metered_external_refused_when_over_budget(session_factory, company_with_budget):
    company_id = company_with_budget  # 10_000c
    meter = CostMeter(session_factory)
    called = {"ran": False}

    async def action():
        called["ran"] = True
        return 1, None, None

    with pytest.raises(BudgetExceeded):
        await meter.metered_external(
            company_id=company_id,
            agent_id=None,
            task_id=None,
            estimated_cents=10_001,
            vendor="v",
            sku=None,
            action=action,
        )
    assert called["ran"] is False  # reserved BEFORE the irreversible action
