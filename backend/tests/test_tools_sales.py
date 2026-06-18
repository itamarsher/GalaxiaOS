"""Tests for the sales tools module.

The sales tools are now backed by the self-coded CRM: a lead becomes a real
contact, a deal update a real deal, a follow-up a real activity. The structural
checks are DB-free; the behavioural checks persist and read back through the CRM.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Agent, AgentRun, CrmContact, CrmDeal, MetricSignal, Task
from app.models.enums import AgentRole, CrmDealStage, RunStatus, RunTrigger, TaskStatus
from app.runtime.tools import TOOL_SPECS, execute_tool
from app.runtime.tools.sales import DEAL_STAGES, HANDLERS, SPECS
from tests.conftest import requires_db

SALES_TOOL_NAMES = ("log_lead", "update_deal", "schedule_followup")


# ── Structural (DB-free) ──────────────────────────────────────────────────────


def test_sales_tools_registered():
    names = {s.name for s in TOOL_SPECS}
    for expected in SALES_TOOL_NAMES:
        assert expected in names


def test_specs_have_object_schema():
    for spec in SPECS:
        assert spec.input_schema["type"] == "object"
        assert "properties" in spec.input_schema


def test_handlers_match_specs():
    assert set(HANDLERS) == {s.name for s in SPECS}


def test_spec_names_are_exactly_assigned():
    assert {s.name for s in SPECS} == set(SALES_TOOL_NAMES)


def test_update_deal_schema_lists_stages():
    spec = next(s for s in SPECS if s.name == "update_deal")
    assert spec.input_schema["properties"]["stage"]["enum"] == list(DEAL_STAGES)
    assert DEAL_STAGES == tuple(s.value for s in CrmDealStage)


# ── Behavioural (DB-backed) ───────────────────────────────────────────────────


async def _make_growth_task(session_factory, company_id):
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.growth, name="Growth")
        db.add(agent)
        await db.flush()
        run = AgentRun(
            company_id=company_id, trigger=RunTrigger.onboarding, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company_id,
            run_id=run.id,
            root_run_id=run.id,
            agent_id=agent.id,
            goal="sell",
            status=TaskStatus.running,
        )
        db.add(task)
        await db.commit()
        return agent, task


@requires_db
async def test_log_lead_persists_contact(session_factory, company_with_budget):
    company_id = company_with_budget
    agent, task = await _make_growth_task(session_factory, company_id)

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            object(),
            agent=agent,
            task=task,
            name="log_lead",
            args={"name": "Ada Lovelace", "email": "ada@x.io", "company": "Analytical"},
        )
        await db.commit()
    assert outcome.is_error is False

    async with session_factory() as db:
        contacts = (await db.scalars(select(CrmContact))).all()
    assert len(contacts) == 1
    assert contacts[0].email == "ada@x.io"
    assert contacts[0].company_name == "Analytical"


@requires_db
async def test_update_deal_won_records_revenue(session_factory, company_with_budget):
    company_id = company_with_budget
    agent, task = await _make_growth_task(session_factory, company_id)

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            object(),
            agent=agent,
            task=task,
            name="update_deal",
            args={"lead": "Acme", "stage": "won", "amount_cents": 50_000},
        )
        await db.commit()
    assert outcome.is_error is False

    async with session_factory() as db:
        deals = (await db.scalars(select(CrmDeal))).all()
        revenue = (
            await db.scalars(select(MetricSignal).where(MetricSignal.name == "revenue"))
        ).all()
    assert len(deals) == 1
    assert deals[0].stage is CrmDealStage.won
    assert deals[0].closed_at is not None
    assert len(revenue) == 1
    assert revenue[0].value == 500.0


@requires_db
async def test_update_deal_rejects_unknown_stage(session_factory, company_with_budget):
    company_id = company_with_budget
    agent, task = await _make_growth_task(session_factory, company_id)
    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            object(),
            agent=agent,
            task=task,
            name="update_deal",
            args={"lead": "Acme", "stage": "negotiating"},
        )
    assert outcome.is_error is True
    assert "invalid stage" in outcome.observation
