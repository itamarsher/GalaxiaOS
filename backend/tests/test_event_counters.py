"""Per-company event counters: atomic increments, tenant scoping, best-effort."""

from __future__ import annotations

from app.db import set_tenant
from app.models.enums import EventType
from app.services import event_counters as ec
from tests.conftest import requires_db


@requires_db
async def test_increment_accumulates_and_reads_back(session_factory, company_with_budget):
    cid = company_with_budget
    async with session_factory() as db:
        await set_tenant(db, cid)
        await ec.record(db, company_id=cid, event_type=EventType.llm_call)
        await ec.record(db, company_id=cid, event_type=EventType.llm_call, n=2)
        await ec.record(db, company_id=cid, event_type=EventType.tool_call)
        await db.commit()

    async with session_factory() as db:
        await set_tenant(db, cid)
        totals = await ec.totals(db, company_id=cid)
        snap = await ec.snapshot(db, company_id=cid)

    assert totals == {"llm_call": 3, "tool_call": 1}
    # snapshot is sorted by count desc and carries last_event_at.
    assert [c["event_type"] for c in snap] == ["llm_call", "tool_call"]
    assert all(c["last_event_at"] for c in snap)


@requires_db
async def test_zero_or_negative_is_noop(session_factory, company_with_budget):
    cid = company_with_budget
    async with session_factory() as db:
        await set_tenant(db, cid)
        await ec.record(db, company_id=cid, event_type=EventType.task_failed, n=0)
        await ec.record(db, company_id=cid, event_type=EventType.task_failed, n=-5)
        await db.commit()
    async with session_factory() as db:
        await set_tenant(db, cid)
        assert await ec.totals(db, company_id=cid) == {}


@requires_db
async def test_string_event_type_accepted(session_factory, company_with_budget):
    cid = company_with_budget
    async with session_factory() as db:
        await set_tenant(db, cid)
        await ec.record(db, company_id=cid, event_type="custom_beat")
        await db.commit()
    async with session_factory() as db:
        await set_tenant(db, cid)
        assert (await ec.totals(db, company_id=cid))["custom_beat"] == 1


@requires_db
async def test_standalone_opens_its_own_session(session_factory, company_with_budget):
    cid = company_with_budget
    await ec.record_standalone(
        company_id=cid, event_type=EventType.error_escalated, n=3, session_factory=session_factory
    )
    async with session_factory() as db:
        await set_tenant(db, cid)
        assert (await ec.totals(db, company_id=cid))["error_escalated"] == 3


@requires_db
async def test_increment_failure_does_not_poison_outer_txn(
    session_factory, company_with_budget, monkeypatch
):
    """A counter write that raises must roll back only itself (SAVEPOINT), leaving
    the surrounding transaction usable — counting is telemetry, never fatal."""
    cid = company_with_budget

    async def _boom(*a, **k):
        raise RuntimeError("counter backend down")

    async with session_factory() as db:
        await set_tenant(db, cid)
        # Sabotage the execute used by the increment for one call.
        monkeypatch.setattr(db, "execute", _boom)
        await ec.record(db, company_id=cid, event_type=EventType.llm_call)  # swallowed
        monkeypatch.undo()
        # The outer transaction is still healthy: a normal write commits fine.
        await ec.record(db, company_id=cid, event_type=EventType.tool_call)
        await db.commit()

    async with session_factory() as db:
        await set_tenant(db, cid)
        assert (await ec.totals(db, company_id=cid)) == {"tool_call": 1}
