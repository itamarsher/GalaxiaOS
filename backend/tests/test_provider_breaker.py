"""A provider funding/auth failure must halt the company and be escalated — not fail silently.

When the LLM provider rejects calls because the account is out of credit (or the key
is invalid), every task fails identically and no retry helps. Before this, the CEO's
run just died with a generic failed task and the org went quiet with no explanation.
Now the run trips a dedicated *provider* circuit breaker, posts an operator-actionable
alert to the founder DM, and surfaces the block through the run gate and the MCP
snapshot so a founder's AI operator sees it (RFC: verified-over-described visibility).
"""

from __future__ import annotations

import os
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Agent, AgentRun, ChatMessage, Company, Mission, Task, User
from app.models.enums import (
    AgentRole,
    CompanyStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.providers.anthropic import _is_billing_error
from app.providers.base import ProviderError
from app.runtime import breakers, orchestrator
from app.runtime.context import RuntimeContext
from tests.conftest import requires_db

# ── provider-boundary classification (no DB) ──────────────────────────────────


def test_is_billing_error_distinguishes_funding_from_malformed():
    """A credit/billing 400 is recognised; an ordinary bad request is not."""
    assert _is_billing_error(Exception("Your credit balance is too low to access the API"))
    assert _is_billing_error(Exception("Please go to Plans & Billing to purchase credits"))
    # A genuinely malformed request must NOT be misread as a funding problem.
    assert not _is_billing_error(Exception("messages: at least one message is required"))


# ── DB-backed breaker mechanics + run integration ─────────────────────────────


class _ProviderBillingBackend:
    """A backend whose LLM call fails the way an out-of-credit account does."""

    async def run(self, ctx, agent, task):
        raise ProviderError(
            "Anthropic rejected the request: the account's credit balance is too low.",
            kind="billing",
        )


async def _active_company_with_ceo(db):
    user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
    db.add(user)
    await db.flush()
    company = Company(owner_user_id=user.id, name="T", status=CompanyStatus.active)
    db.add(company)
    await db.flush()
    db.add(Mission(company_id=company.id, raw_text="Grow.", constraints=[]))
    ceo = Agent(company_id=company.id, role=AgentRole.ceo, name="CEO")
    db.add(ceo)
    await db.flush()
    return company, ceo


async def _queued_ceo_task(db, company, ceo):
    run = AgentRun(company_id=company.id, trigger=RunTrigger.scheduled, status=RunStatus.running)
    db.add(run)
    await db.flush()
    run.root_run_id = run.id
    task = Task(
        company_id=company.id, run_id=run.id, root_run_id=run.id, agent_id=ceo.id,
        goal="plan the company", status=TaskStatus.queued,
    )
    db.add(task)
    await db.flush()
    return task


@requires_db
async def test_provider_block_trips_breaker_fails_task_and_alerts_founder(
    session_factory, monkeypatch
):
    async with session_factory() as db:
        company, ceo = await _active_company_with_ceo(db)
        task = await _queued_ceo_task(db, company, ceo)
        await db.commit()
        company_id, task_id = company.id, task.id

    monkeypatch.setattr(
        orchestrator, "get_backend", lambda backend_type: _ProviderBillingBackend()
    )

    engine = create_async_engine(os.environ["ABOS_TEST_DATABASE_URL"], future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _noop_enqueue(task_id, *, delay_seconds=0):
        raise AssertionError("a provider block is terminal — no review task to enqueue")

    ctx = RuntimeContext(session_factory=factory, cost_meter=None, provider=None,
                         enqueue_task=_noop_enqueue)
    try:
        # A provider block is handled gracefully (returns), not re-raised.
        result = await orchestrator.run_task(ctx, task_id)
        assert result["status"] == TaskStatus.failed.value

        async with factory() as db:
            # Task is terminally failed with the provider reason.
            row = await db.get(Task, task_id)
            assert row.status is TaskStatus.failed
            assert "credit balance" in row.output["error"]

            # The provider breaker is tripped → the company is halted.
            reason = await breakers.provider_breaker_reason(db, company_id)
            assert reason is not None and "credit balance" in reason

            # The founder was escalated to: an alert lands in the CEO↔founder DM.
            msgs = (
                await db.scalars(
                    select(ChatMessage).where(ChatMessage.company_id == company_id)
                )
            ).all()
            assert any("pause the company" in m.body for m in msgs)
    finally:
        await engine.dispose()


@requires_db
async def test_tripped_provider_breaker_blocks_further_tasks(session_factory):
    """Once tripped, the pre-task breaker gate blocks every task (stops doomed cycles)."""
    async with session_factory() as db:
        company, ceo = await _active_company_with_ceo(db)
        task = await _queued_ceo_task(db, company, ceo)
        # Un-tripped: the gate passes.
        assert (await breakers.check_before_task(db, task)).ok
        await breakers.trip_provider_breaker(db, company.id, "out of credit")
        verdict = await breakers.check_before_task(db, task)
        assert not verdict.ok and "provider" in verdict.reason


@requires_db
async def test_clear_provider_breaker_rearms(session_factory):
    """An operator fix (top-up / funded key) re-arms the breaker so cycles resume."""
    async with session_factory() as db:
        company, _ = await _active_company_with_ceo(db)
        await breakers.trip_provider_breaker(db, company.id, "out of credit")
        assert await breakers.provider_breaker_reason(db, company.id) is not None
        assert await breakers.clear_provider_breaker(db, company.id) is True
        assert await breakers.provider_breaker_reason(db, company.id) is None
        # Idempotent: clearing an already-armed breaker is a no-op.
        assert await breakers.clear_provider_breaker(db, company.id) is False


@requires_db
async def test_run_gate_and_snapshot_surface_provider_block(session_factory):
    """The run gate reports ``provider_blocked`` and the MCP snapshot raises an alert."""
    from app.api.founder_mcp import _snapshot
    from app.models import Budget
    from app.models.enums import BudgetPeriod
    from app.services import runs as runs_svc

    async with session_factory() as db:
        company, _ = await _active_company_with_ceo(db)
        db.add(Budget(company_id=company.id, period=BudgetPeriod.monthly, limit_cents=50_000))
        await breakers.trip_provider_breaker(db, company.id, "credit balance is too low")
        await db.flush()

        # Run gate: a new cycle can't start, and says exactly why.
        status = await runs_svc.cycle_status(db, company)
        assert status.can_start is False and status.reason == "provider_blocked"

        # MCP snapshot: the block is escalated to the operator as a critical alert.
        snap = await _snapshot(db, company)
        alerts = snap["alerts"]
        assert len(alerts) == 1
        assert alerts[0]["kind"] == "provider_blocked"
        assert alerts[0]["severity"] == "critical"
        assert "add_provider_key" in alerts[0]["action"]
