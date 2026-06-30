"""Graceful handling of an exhausted LLM-provider balance.

Covers the full arc: detecting the vendor's "insufficient_credits" refusal in the
agent loop pauses the whole fleet and raises one CEO→founder ask; the founder
saying they reloaded re-validates the account and only resumes the paused tasks
once balance is actually confirmed; an empty account resurfaces and schedules a
re-check. Also pins the runtime guard (new tasks park instead of re-failing) and
restart recovery (the re-check is re-armed).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Agent, AgentRun, DecisionRequest, Task
from app.models.enums import (
    AgentRole,
    DecisionKind,
    DecisionStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.providers.base import LLMResponse, ProviderError, Usage
from app.runtime import orchestrator
from app.runtime.context import RuntimeContext
from app.runtime.cost_meter import CostMeter
from app.services import provider_balance
from tests.conftest import requires_db

pytestmark = requires_db


# ── Fakes ─────────────────────────────────────────────────────────────────────
class _BalanceProvider:
    """A provider whose probe call either succeeds or reports an empty balance."""

    name = "anthropic"
    default_models = {"cheap": "claude-haiku-4-5"}

    def __init__(self, *, ok: bool):
        self.ok = ok
        self.calls = 0

    async def complete(self, **kwargs):
        self.calls += 1
        if self.ok:
            return LLMResponse(text="pong", usage=Usage(), model="claude-haiku-4-5")
        raise ProviderError("credit balance is too low", kind="insufficient_credits")


class _RecordingBackend:
    """A backend that either raises the balance error or records that it ran."""

    def __init__(self, *, raise_balance: bool):
        self.raise_balance = raise_balance
        self.ran = 0

    async def run(self, ctx, agent, task) -> dict:
        self.ran += 1
        if self.raise_balance:
            raise ProviderError("credit balance is too low", kind="insufficient_credits")
        return {"status": "done"}


# ── DB helpers ────────────────────────────────────────────────────────────────
async def _add_ceo(db, company_id):
    agent = Agent(company_id=company_id, role=AgentRole.ceo, name="CEO")
    db.add(agent)
    await db.flush()
    return agent.id


async def _add_task(db, company_id, agent_id, *, status):
    run = AgentRun(company_id=company_id, trigger=RunTrigger.onboarding, status=RunStatus.running)
    db.add(run)
    await db.flush()
    run.root_run_id = run.id
    task = Task(
        company_id=company_id,
        run_id=run.id,
        root_run_id=run.id,
        agent_id=agent_id,
        goal="g",
        status=status,
    )
    db.add(task)
    await db.flush()
    return task.id


def _patch_resolve(monkeypatch, provider):
    async def _resolve(db, *, company_id):
        return None if provider is None else (provider, "sk-test")

    monkeypatch.setattr(provider_balance.apikeys, "resolve_provider", _resolve)


# ── handle_exhaustion ─────────────────────────────────────────────────────────
async def test_exhaustion_pauses_live_work_and_asks_founder(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        ceo = await _add_ceo(db, company_id)
        queued = await _add_task(db, company_id, ceo, status=TaskStatus.queued)
        running = await _add_task(db, company_id, ceo, status=TaskStatus.running)
        waiting = await _add_task(db, company_id, ceo, status=TaskStatus.waiting_approval)
        await db.commit()

        decision = await provider_balance.handle_exhaustion(
            db, company_id=company_id, provider_name="anthropic"
        )
        await db.commit()

    async with session_factory() as db:
        # queued + running parked; waiting_approval left on its own gate.
        assert (await db.get(Task, queued)).status is TaskStatus.paused
        assert (await db.get(Task, running)).status is TaskStatus.paused
        assert (await db.get(Task, waiting)).status is TaskStatus.waiting_approval
        # Exactly one founder ask, attributed to the CEO and marked waiting.
        rows = (await db.scalars(select(DecisionRequest))).all()
        assert len(rows) == 1
        assert rows[0].kind is DecisionKind.provider_balance
        assert rows[0].agent_id == ceo
        assert rows[0].channel_id is not None  # surfaced as a CEO→founder DM
        assert "load more balance" in rows[0].summary.lower()
    assert decision is not None


async def test_exhaustion_is_idempotent(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        ceo = await _add_ceo(db, company_id)
        await _add_task(db, company_id, ceo, status=TaskStatus.queued)
        await db.commit()
        first = await provider_balance.handle_exhaustion(db, company_id=company_id)
        await db.commit()
        # A second failure (e.g. a concurrent task) must not raise a duplicate ask.
        second = await provider_balance.handle_exhaustion(db, company_id=company_id)
        await db.commit()

    assert first is not None and second is None
    async with session_factory() as db:
        rows = (await db.scalars(select(DecisionRequest))).all()
        assert len(rows) == 1
        assert await provider_balance.is_exhausted(db, company_id) is True


# ── attempt_resume ────────────────────────────────────────────────────────────
async def test_resume_when_balance_restored(session_factory, company_with_budget, monkeypatch):
    company_id = company_with_budget
    _patch_resolve(monkeypatch, _BalanceProvider(ok=True))
    async with session_factory() as db:
        ceo = await _add_ceo(db, company_id)
        t1 = await _add_task(db, company_id, ceo, status=TaskStatus.queued)
        await db.commit()
        await provider_balance.handle_exhaustion(db, company_id=company_id)
        await db.commit()

        outcome = await provider_balance.attempt_resume(db, company_id=company_id)
        await db.commit()

    assert outcome.resumed is True
    assert outcome.still_exhausted is False
    assert outcome.resumed_task_ids == [t1]
    async with session_factory() as db:
        assert (await db.get(Task, t1)).status is TaskStatus.queued
        decision = (await db.scalars(select(DecisionRequest))).all()[0]
        assert decision.status is DecisionStatus.approved
        assert await provider_balance.is_exhausted(db, company_id) is False


async def test_resume_blocked_when_still_insufficient(
    session_factory, company_with_budget, monkeypatch
):
    company_id = company_with_budget
    _patch_resolve(monkeypatch, _BalanceProvider(ok=False))
    async with session_factory() as db:
        ceo = await _add_ceo(db, company_id)
        t1 = await _add_task(db, company_id, ceo, status=TaskStatus.queued)
        await db.commit()
        await provider_balance.handle_exhaustion(db, company_id=company_id)
        await db.commit()

        outcome = await provider_balance.attempt_resume(db, company_id=company_id)
        await db.commit()

    assert outcome.resumed is False
    assert outcome.still_exhausted is True
    assert outcome.resumed_task_ids == []
    async with session_factory() as db:
        # Tasks stay parked; the ask stays open for the founder to retry / auto-recheck.
        assert (await db.get(Task, t1)).status is TaskStatus.paused
        decision = (await db.scalars(select(DecisionRequest))).all()[0]
        assert decision.status is DecisionStatus.pending


class _AuthErrorProvider:
    """Probe raises a non-balance provider error (e.g. a bad key)."""

    name = "anthropic"
    default_models = {"cheap": "claude-haiku-4-5"}

    async def complete(self, **kwargs):
        raise ProviderError("bad key", kind="auth")


async def test_resume_survives_non_balance_probe_error(
    session_factory, company_with_budget, monkeypatch
):
    company_id = company_with_budget
    _patch_resolve(monkeypatch, _AuthErrorProvider())
    async with session_factory() as db:
        ceo = await _add_ceo(db, company_id)
        t1 = await _add_task(db, company_id, ceo, status=TaskStatus.queued)
        await db.commit()
        await provider_balance.handle_exhaustion(db, company_id=company_id)
        await db.commit()
        # A bad key / network blip during validation must not crash or resume —
        # stay paused and signal a re-check.
        outcome = await provider_balance.attempt_resume(db, company_id=company_id)
        await db.commit()

    assert outcome.resumed is False
    assert outcome.still_exhausted is True
    async with session_factory() as db:
        assert (await db.get(Task, t1)).status is TaskStatus.paused


async def test_resume_is_noop_when_not_exhausted(
    session_factory, company_with_budget, monkeypatch
):
    company_id = company_with_budget
    probe = _BalanceProvider(ok=True)
    _patch_resolve(monkeypatch, probe)
    async with session_factory() as db:
        await _add_ceo(db, company_id)
        await db.commit()
        outcome = await provider_balance.attempt_resume(db, company_id=company_id)
        await db.commit()

    # No pending ask → nothing to do, and crucially no probe call is wasted.
    assert outcome.resumed is False
    assert outcome.still_exhausted is False
    assert probe.calls == 0


async def test_resume_without_key_stays_exhausted(
    session_factory, company_with_budget, monkeypatch
):
    company_id = company_with_budget
    _patch_resolve(monkeypatch, None)  # no provider key configured
    async with session_factory() as db:
        ceo = await _add_ceo(db, company_id)
        await _add_task(db, company_id, ceo, status=TaskStatus.queued)
        await db.commit()
        await provider_balance.handle_exhaustion(db, company_id=company_id)
        await db.commit()
        outcome = await provider_balance.attempt_resume(db, company_id=company_id)
        await db.commit()

    assert outcome.resumed is False
    assert outcome.still_exhausted is True


# ── dispatch_outcome (pure plumbing) ──────────────────────────────────────────
async def test_dispatch_resumes_tasks_without_recheck():
    t1, t2, cid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tasks: list = []
    rechecks: list = []

    async def eq(task_id, *, delay_seconds=0):
        tasks.append((task_id, delay_seconds))

    async def er(company_id, *, delay_seconds=0):
        rechecks.append((company_id, delay_seconds))

    await provider_balance.dispatch_outcome(
        provider_balance.ResumeOutcome(resumed=True, resumed_task_ids=[t1, t2]),
        company_id=cid,
        enqueue_task=eq,
        enqueue_recheck=er,
        recheck_delay_seconds=900,
    )
    assert tasks == [(t1, 0), (t2, 0)]
    assert rechecks == []  # resumed → no resurface scheduled


async def test_dispatch_schedules_recheck_when_still_exhausted():
    cid = uuid.uuid4()
    rechecks: list = []

    async def er(company_id, *, delay_seconds=0):
        rechecks.append((company_id, delay_seconds))

    async def eq(task_id, *, delay_seconds=0):  # pragma: no cover - not called
        raise AssertionError("no tasks to enqueue")

    await provider_balance.dispatch_outcome(
        provider_balance.ResumeOutcome(still_exhausted=True),
        company_id=cid,
        enqueue_task=eq,
        enqueue_recheck=er,
        recheck_delay_seconds=900,
    )
    assert rechecks == [(cid, 900)]


# ── orchestrator integration ──────────────────────────────────────────────────
def _ctx(session_factory) -> RuntimeContext:
    class _Provider:
        name = "anthropic"

    async def _enqueue(task_id, *, delay_seconds=0):
        return None

    return RuntimeContext(
        session_factory=session_factory,
        cost_meter=CostMeter(session_factory),
        provider=_Provider(),
        enqueue_task=_enqueue,
    )


async def test_run_task_catches_balance_error_and_pauses(
    session_factory, company_with_budget, monkeypatch
):
    company_id = company_with_budget
    async with session_factory() as db:
        ceo = await _add_ceo(db, company_id)
        other = await _add_task(db, company_id, ceo, status=TaskStatus.queued)
        task_id = await _add_task(db, company_id, ceo, status=TaskStatus.queued)
        await db.commit()

    backend = _RecordingBackend(raise_balance=True)
    monkeypatch.setattr(orchestrator, "get_backend", lambda _t: backend)

    result = await orchestrator.run_task(_ctx(session_factory), task_id)

    assert result["status"] == TaskStatus.paused.value
    async with session_factory() as db:
        # The triggering task and the rest of the live fleet are parked, and the
        # founder ask was raised exactly once.
        assert (await db.get(Task, task_id)).status is TaskStatus.paused
        assert (await db.get(Task, other)).status is TaskStatus.paused
        decisions = (await db.scalars(select(DecisionRequest))).all()
        assert len(decisions) == 1
        assert decisions[0].kind is DecisionKind.provider_balance


async def test_run_task_parks_new_work_while_exhausted(
    session_factory, company_with_budget, monkeypatch
):
    company_id = company_with_budget
    async with session_factory() as db:
        ceo = await _add_ceo(db, company_id)
        # Flag the company exhausted first, then enqueue brand-new work — the kind
        # a cron or resume race could create while the account is still dry.
        await provider_balance.handle_exhaustion(db, company_id=company_id)
        task_id = await _add_task(db, company_id, ceo, status=TaskStatus.queued)
        await db.commit()

    backend = _RecordingBackend(raise_balance=False)
    monkeypatch.setattr(orchestrator, "get_backend", lambda _t: backend)

    result = await orchestrator.run_task(_ctx(session_factory), task_id)

    # Parked up front — the backend (and another failing call) is never reached.
    assert result["status"] == TaskStatus.paused.value
    assert backend.ran == 0
    async with session_factory() as db:
        assert (await db.get(Task, task_id)).status is TaskStatus.paused


# ── restart recovery ──────────────────────────────────────────────────────────
async def test_recovery_rearms_recheck_for_exhausted_company(
    session_factory, company_with_budget, monkeypatch
):
    from app.jobs import recovery, scheduled

    monkeypatch.setattr(recovery, "SessionLocal", session_factory)
    monkeypatch.setattr(scheduled, "SessionLocal", session_factory)

    company_id = company_with_budget
    async with session_factory() as db:
        ceo = await _add_ceo(db, company_id)
        await _add_task(db, company_id, ceo, status=TaskStatus.queued)
        await db.commit()
        await provider_balance.handle_exhaustion(db, company_id=company_id)
        await db.commit()

    task_calls: list = []
    recheck_calls: list = []

    async def eq(task_id, *, delay_seconds=0):
        task_calls.append((task_id, delay_seconds))

    async def er(cid, *, delay_seconds=0):
        recheck_calls.append((cid, delay_seconds))

    summary = await recovery.recover_pending_work(eq, er)

    # Paused tasks are NOT re-enqueued as work; instead a balance re-check is armed.
    assert task_calls == []
    assert recheck_calls == [(company_id, 0)]
    assert summary["restarted"] == 0


async def test_recovery_ignores_healthy_company(
    session_factory, company_with_budget, monkeypatch
):
    from app.jobs import recovery, scheduled

    monkeypatch.setattr(recovery, "SessionLocal", session_factory)
    monkeypatch.setattr(scheduled, "SessionLocal", session_factory)

    async with session_factory() as db:
        await _add_ceo(db, company_with_budget)
        await db.commit()

    recheck_calls: list = []

    async def er(cid, *, delay_seconds=0):
        recheck_calls.append((cid, delay_seconds))

    async def eq(task_id, *, delay_seconds=0):
        return None

    await recovery.recover_pending_work(eq, er)
    assert recheck_calls == []  # not exhausted → no re-check armed
