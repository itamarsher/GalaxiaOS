"""Tests for :class:`MarketplaceBackend` — the hired-agent execution seam.

The backend simulates remote execution but is otherwise *functional*: it meters
the flat invocation fee and finalises the task through the shared
:func:`app.services.tasks.finalize`, so a hired agent's result winds down exactly
like a native one — including propagating a delegated result back to the parent/CEO
via company memory and dropping the working transcript.
"""

from __future__ import annotations

from app.models import Agent, AgentRun, Task
from app.models.enums import (
    AgentBackendType,
    AgentRole,
    MemoryType,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.runtime.backends import get_backend
from app.runtime.backends.marketplace import MarketplaceBackend
from app.runtime.backends.native import NativeBackend
from app.runtime.context import RuntimeContext
from app.runtime.cost_meter import CostMeter
from tests.conftest import requires_db


# ── DB-free unit tests ───────────────────────────────────────────────────────
def test_backend_registry_resolves_types():
    assert isinstance(get_backend("marketplace"), MarketplaceBackend)
    assert isinstance(get_backend("native"), NativeBackend)


def test_unknown_backend_type_raises():
    try:
        get_backend("external")
    except NotImplementedError:
        pass
    else:  # pragma: no cover - guard
        raise AssertionError("expected NotImplementedError for a reserved backend")


# ── DB-backed helpers ────────────────────────────────────────────────────────
def _make_ctx(session_factory, recorded_memory, monkeypatch):
    """A RuntimeContext with a real CostMeter; memory writes are captured, not embedded.

    The test schema omits ``memory_entries`` (pgvector), so :func:`memory.write` is
    stubbed to record its call instead of touching the DB — letting us assert *that*
    a delegated result propagates without needing the vector table.
    """
    from app.services import memory

    async def _record(db, **kwargs):
        recorded_memory.append(kwargs)
        return None

    monkeypatch.setattr(memory, "write", _record)
    return RuntimeContext(
        session_factory=session_factory,
        cost_meter=CostMeter(session_factory),
        provider=None,
        enqueue_task=lambda *a, **k: None,
    )


async def _scaffold_marketplace(session_factory, company_id):
    """A CEO parent task and a hired marketplace child it dispatched (with a transcript)."""
    async with session_factory() as db:
        ceo = Agent(company_id=company_id, role=AgentRole.ceo, name="CEO")
        hired = Agent(
            company_id=company_id,
            role=AgentRole.growth,
            name="Apex Growth Hacker",
            backend_type=AgentBackendType.marketplace,
            invocation_price_cents=200,
        )
        db.add_all([ceo, hired])
        await db.flush()
        run = AgentRun(
            company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        parent = Task(
            company_id=company_id, run_id=run.id, root_run_id=run.id,
            agent_id=ceo.id, goal="grow the company", status=TaskStatus.running,
        )
        db.add(parent)
        await db.flush()
        child = Task(
            company_id=company_id, run_id=run.id, root_run_id=run.id,
            agent_id=hired.id, parent_task_id=parent.id, depth=1,
            goal="run a paid acquisition experiment", status=TaskStatus.running,
            transcript=[{"role": "user", "content": "Begin"}],
        )
        db.add(child)
        await db.commit()
        return hired, child


# ── run(): metering + shared finalisation ────────────────────────────────────
@requires_db
async def test_marketplace_run_finalises_like_native(
    session_factory, company_with_budget, monkeypatch
):
    hired, child = await _scaffold_marketplace(session_factory, company_with_budget)
    recorded: list[dict] = []
    ctx = _make_ctx(session_factory, recorded, monkeypatch)
    result = await MarketplaceBackend().run(ctx, hired, child)

    assert result["status"] == TaskStatus.done.value

    async with session_factory() as db:
        row = await db.get(Task, child.id)
        assert row.status is TaskStatus.done
        # Routed through the shared finalize: transcript dropped, cost stamped from
        # the metered invocation fee (200c). The old hand-rolled path left the
        # transcript intact.
        assert row.transcript is None
        assert row.cost_cents == 200

    # A delegated result (parent_task_id set) propagates back to the parent/CEO as a
    # ``Result:`` memory entry — the piece the hand-rolled finalize used to skip.
    titles = [m["title"] for m in recorded]
    assert any(t.startswith("Result:") for t in titles)
    result_entry = next(m for m in recorded if m["title"].startswith("Result:"))
    assert result_entry["type"] is MemoryType.result
    assert result_entry["source_task_id"] == child.id


@requires_db
async def test_marketplace_run_meters_the_invocation_fee(
    session_factory, company_with_budget, monkeypatch
):
    from app.services import budget as budget_svc

    hired, child = await _scaffold_marketplace(session_factory, company_with_budget)
    ctx = _make_ctx(session_factory, [], monkeypatch)
    await MarketplaceBackend().run(ctx, hired, child)

    async with session_factory() as db:
        spent = await budget_svc.agent_spent(db, hired.id)
    assert spent == 200
