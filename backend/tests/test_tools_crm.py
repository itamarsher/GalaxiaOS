"""Tests for the self-coded CRM (tools + service).

Structural checks are DB-free; the behavioural checks exercise the real
persistence and read-back that distinguishes this CRM from the old fabricated
stubs (create → search → advance pipeline → log activity → timeline).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from sqlalchemy import select

from app.models import CrmActivity, CrmContact, CrmDeal, MetricSignal
from app.models.enums import AgentRole, CrmActivityKind, CrmContactStatus, CrmDealStage
from app.runtime.tools import TOOL_SPECS, execute_tool
from app.runtime.tools.crm import (
    ACTIVITY_KINDS,
    CONTACT_STATUSES,
    DEAL_STAGES,
    HANDLERS,
    SPECS,
    _dollars,
    _enum,
    format_deal,
)
from app.services import crm as crm_svc
from tests.conftest import requires_db

CRM_TOOL_NAMES = (
    "crm_save_contact",
    "crm_find_contacts",
    "crm_save_deal",
    "crm_list_deals",
    "crm_log_activity",
    "crm_contact_timeline",
)


# ── Structural (DB-free) ──────────────────────────────────────────────────────


def test_crm_tools_registered():
    names = {s.name for s in TOOL_SPECS}
    for expected in CRM_TOOL_NAMES:
        assert expected in names


def test_handlers_match_specs():
    assert set(HANDLERS) == {s.name for s in SPECS}
    assert {s.name for s in SPECS} == set(CRM_TOOL_NAMES)


def test_specs_have_object_schema():
    for spec in SPECS:
        assert spec.input_schema["type"] == "object"
        assert "properties" in spec.input_schema


def test_enum_lists_track_the_models():
    assert DEAL_STAGES == tuple(s.value for s in CrmDealStage)
    assert CONTACT_STATUSES == tuple(s.value for s in CrmContactStatus)
    assert ACTIVITY_KINDS == tuple(k.value for k in CrmActivityKind)


def test_enum_helper_normalizes_and_rejects():
    assert _enum("WON", CrmDealStage, "stage") is CrmDealStage.won
    assert _enum(" lead ", CrmContactStatus, "status") is CrmContactStatus.lead
    try:
        _enum("nope", CrmDealStage, "stage")
    except ValueError as exc:
        assert "invalid stage" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_format_helpers():
    assert _dollars(12345) == "$123.45"
    assert _dollars(None) == "$0.00"
    deal = SimpleNamespace(title="Acme", stage=CrmDealStage.won, amount_cents=10000)
    assert format_deal(deal) == "Acme -> won ($100.00)"


# ── Behavioural (DB-backed) ───────────────────────────────────────────────────


def _task(company_id):
    """Minimal stand-in: the CRM handlers only read ``task.company_id``."""
    return SimpleNamespace(company_id=company_id, id=None)


def _agent(*, role=AgentRole.growth, access_labels=("customers",)):
    """A CRM-cleared agent by default (has the ``customers`` label)."""
    return SimpleNamespace(
        id=uuid.uuid4(), role=role,
        access_labels=None if access_labels is None else list(access_labels),
    )


@requires_db
async def test_save_contact_upserts_by_email(session_factory, company_with_budget):
    company_id = company_with_budget
    task = _task(company_id)

    async with session_factory() as db:
        first = await execute_tool(
            db,
            object(),
            agent=None,
            task=task,
            name="crm_save_contact",
            args={"name": "Grace Hopper", "email": "grace@navy.mil", "status": "lead"},
        )
        await db.commit()
    assert first.is_error is False

    # Re-saving the same email updates (status change), does not duplicate.
    async with session_factory() as db:
        second = await execute_tool(
            db,
            object(),
            agent=None,
            task=task,
            name="crm_save_contact",
            args={"email": "grace@navy.mil", "status": "qualified", "title": "Admiral"},
        )
        await db.commit()
    assert second.is_error is False

    async with session_factory() as db:
        contacts = (await db.scalars(select(CrmContact))).all()
    assert len(contacts) == 1
    assert contacts[0].status is CrmContactStatus.qualified
    assert contacts[0].title == "Admiral"


@requires_db
async def test_find_contacts_filters(session_factory, company_with_budget):
    company_id = company_with_budget
    task = _task(company_id)
    async with session_factory() as db:
        for name, status in [("Alice", "lead"), ("Bob", "customer"), ("Alicia", "lead")]:
            await crm_svc.upsert_contact(
                db, company_id=company_id, name=name, status=CrmContactStatus(status)
            )
        await db.commit()

    async with session_factory() as db:
        by_query = await execute_tool(
            db,
            object(),
            agent=_agent(),
            task=task,
            name="crm_find_contacts",
            args={"query": "ali"},
        )
        by_status = await execute_tool(
            db,
            object(),
            agent=_agent(),
            task=task,
            name="crm_find_contacts",
            args={"status": "customer"},
        )
    assert "Alice" in by_query.observation and "Alicia" in by_query.observation
    assert "Bob" not in by_query.observation
    assert "Bob" in by_status.observation and "Alice" not in by_status.observation


@requires_db
async def test_save_deal_links_contact_and_won_records_revenue(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    task = _task(company_id)
    async with session_factory() as db:
        await crm_svc.upsert_contact(db, company_id=company_id, name="Carol", email="carol@x.io")
        await db.commit()

    # Create a deal linked to the contact by email.
    async with session_factory() as db:
        created = await execute_tool(
            db,
            object(),
            agent=None,
            task=task,
            name="crm_save_deal",
            args={"title": "Carol Expansion", "stage": "proposal", "contact": "carol@x.io"},
        )
        await db.commit()
    assert created.is_error is False

    # Advance the same deal (by title) to won with an amount → revenue metric.
    async with session_factory() as db:
        won = await execute_tool(
            db,
            object(),
            agent=None,
            task=task,
            name="crm_save_deal",
            args={"title": "Carol Expansion", "stage": "won", "amount_cents": 250_000},
        )
        await db.commit()
    assert won.is_error is False

    async with session_factory() as db:
        deals = (await db.scalars(select(CrmDeal))).all()
        revenue = (
            await db.scalars(select(MetricSignal).where(MetricSignal.name == "revenue"))
        ).all()
        contact = (await db.scalars(select(CrmContact))).one()
    assert len(deals) == 1  # advanced, not duplicated
    assert deals[0].stage is CrmDealStage.won
    assert deals[0].contact_id == contact.id
    assert len(revenue) == 1
    assert revenue[0].value == 2500.0


@requires_db
async def test_log_activity_and_timeline(session_factory, company_with_budget):
    company_id = company_with_budget
    task = _task(company_id)
    async with session_factory() as db:
        contact, _ = await crm_svc.upsert_contact(
            db, company_id=company_id, name="Dave", email="dave@x.io"
        )
        await db.commit()

    async with session_factory() as db:
        logged = await execute_tool(
            db,
            object(),
            agent=None,
            task=task,
            name="crm_log_activity",
            args={"kind": "call", "subject": "intro call", "contact": "dave@x.io"},
        )
        await db.commit()
    assert logged.is_error is False

    async with session_factory() as db:
        activities = (await db.scalars(select(CrmActivity))).all()
        timeline = await execute_tool(
            db,
            object(),
            agent=_agent(),
            task=task,
            name="crm_contact_timeline",
            args={"contact": "Dave"},
        )
    assert len(activities) == 1
    assert activities[0].kind is CrmActivityKind.call
    assert activities[0].contact_id == contact.id
    assert "Dave" in timeline.observation
    assert "intro call" in timeline.observation


@requires_db
async def test_crm_reads_gated_on_customers_label(session_factory, company_with_budget):
    """An agent without the ``customers`` label can't read the CRM; the CEO bypasses."""
    company_id = company_with_budget
    task = _task(company_id)
    async with session_factory() as db:
        await crm_svc.upsert_contact(db, company_id=company_id, name="Eve", email="eve@x.io")
        await db.commit()

    uncleared = _agent(role=AgentRole.finance, access_labels=["financial"])
    ceo = _agent(role=AgentRole.ceo, access_labels=None)
    async with session_factory() as db:
        for name in ("crm_find_contacts", "crm_list_deals"):
            out = await execute_tool(db, object(), agent=uncleared, task=task, name=name, args={})
            assert out.is_error and "customer data" in out.observation
        tl = await execute_tool(
            db, object(), agent=uncleared, task=task,
            name="crm_contact_timeline", args={"contact": "Eve"},
        )
        assert tl.is_error and "customer data" in tl.observation

        # The CEO sees it all.
        out = await execute_tool(db, object(), agent=ceo, task=task,
                                 name="crm_find_contacts", args={"query": "eve"})
        assert not out.is_error and "Eve" in out.observation


@requires_db
async def test_list_deals_reports_pipeline(session_factory, company_with_budget):
    company_id = company_with_budget
    task = _task(company_id)
    async with session_factory() as db:
        await crm_svc.upsert_deal(
            db, company_id=company_id, title="A", stage=CrmDealStage.won, amount_cents=10000
        )
        await crm_svc.upsert_deal(
            db, company_id=company_id, title="B", stage=CrmDealStage.new, amount_cents=20000
        )
        await db.commit()

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            object(),
            agent=_agent(),
            task=task,
            name="crm_list_deals",
            args={},
        )
    assert "Pipeline:" in outcome.observation
    assert "won: 1 deal(s), $100.00" in outcome.observation
    assert "new: 1 deal(s), $200.00" in outcome.observation
