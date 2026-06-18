"""Tests for the CEO audit loop: delegated results pass through ``auditing``.

A result the CEO dispatched lands in ``auditing`` and the CEO is woken to review
it; ``audit_task`` then transitions it forward (approve → done) or backward
(reopen → re-queued with comments the agent sees on resume).
"""

from __future__ import annotations

from app.config import settings
from app.models import Agent, AgentRun, Task
from app.models.enums import AgentRole, RunStatus, RunTrigger, TaskStatus
from app.runtime.tools import TOOL_SPECS, execute_tool
from app.services import tasks as task_svc
from tests.conftest import requires_db


class _Ctx:
    """Minimal RuntimeContext stand-in capturing enqueue calls."""

    def __init__(self):
        self.enqueued: list = []

    async def enqueue_task(self, task_id, **kwargs):
        self.enqueued.append(task_id)


# ── DB-free unit tests ───────────────────────────────────────────────────────
def test_audit_task_registered():
    spec = next((s for s in TOOL_SPECS if s.name == "audit_task"), None)
    assert spec is not None
    assert spec.input_schema["properties"]["decision"]["enum"] == ["approve", "reopen"]
    assert spec.input_schema["required"] == ["task_id", "decision"]


def test_auditing_status_exists():
    assert TaskStatus.auditing.value == "auditing"


def test_retry_task_registered():
    spec = next((s for s in TOOL_SPECS if s.name == "retry_task"), None)
    assert spec is not None
    assert spec.input_schema["properties"]["decision"]["enum"] == ["retry", "abandon"]
    assert spec.input_schema["required"] == ["task_id", "decision"]


# ── DB-backed fixtures/helpers ───────────────────────────────────────────────
async def _scaffold(session_factory, company_id):
    """CEO + growth agents, a CEO parent task, and a growth child it dispatched."""
    async with session_factory() as db:
        ceo = Agent(company_id=company_id, role=AgentRole.ceo, name="CEO")
        growth = Agent(company_id=company_id, role=AgentRole.growth, name="Gigi")
        db.add_all([ceo, growth])
        await db.flush()
        run = AgentRun(
            company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        parent = Task(
            company_id=company_id, run_id=run.id, root_run_id=run.id,
            agent_id=ceo.id, goal="run the business", status=TaskStatus.running,
        )
        db.add(parent)
        await db.flush()
        child = Task(
            company_id=company_id, run_id=run.id, root_run_id=run.id,
            agent_id=growth.id, parent_task_id=parent.id, depth=1,
            goal="acquire first users", status=TaskStatus.running,
            transcript=[{"role": "user", "content": "Begin: acquire first users"}],
        )
        db.add(child)
        await db.commit()
        return ceo, growth, parent, child


# ── should_audit ─────────────────────────────────────────────────────────────
@requires_db
async def test_should_audit_for_ceo_dispatched_child(session_factory, company_with_budget):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    async with session_factory() as db:
        g = await db.get(Agent, growth.id)
        c = await db.get(Task, child.id)
        assert await task_svc.should_audit(db, agent=g, task=c) is True


@requires_db
async def test_ceo_own_work_is_not_audited(session_factory, company_with_budget):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    async with session_factory() as db:
        c = await db.get(Agent, ceo.id)
        p = await db.get(Task, parent.id)  # CEO's own root task
        assert await task_svc.should_audit(db, agent=c, task=p) is False


@requires_db
async def test_round_cap_stops_auditing(session_factory, company_with_budget):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    async with session_factory() as db:
        c = await db.get(Task, child.id)
        c.input = {"audit_rounds": settings.max_audit_rounds}
        await db.commit()
    async with session_factory() as db:
        g = await db.get(Agent, growth.id)
        c = await db.get(Task, child.id)
        assert await task_svc.should_audit(db, agent=g, task=c) is False


# ── begin_auditing ───────────────────────────────────────────────────────────
@requires_db
async def test_begin_auditing_parks_child_and_spawns_ceo_task(
    session_factory, company_with_budget
):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    async with session_factory() as db:
        audit_id = await task_svc.begin_auditing(
            db, child_id=child.id, output={"summary": "rough draft"}
        )
        await db.commit()
    assert audit_id is not None

    async with session_factory() as db:
        c = await db.get(Task, child.id)
        assert c.status is TaskStatus.auditing
        assert c.transcript is not None  # preserved for a reopen
        a = await db.get(Task, audit_id)
        assert a.agent_id == ceo.id
        assert a.status is TaskStatus.queued
        assert a.input["audit_target_task_id"] == str(child.id)
        assert str(child.id) in a.goal


# ── audit_task: approve / reopen ─────────────────────────────────────────────
async def _put_child_auditing(session_factory, child_id, summary="meh"):
    async with session_factory() as db:
        c = await db.get(Task, child_id)
        c.status = TaskStatus.auditing
        c.output = {"summary": summary}
        await db.commit()


@requires_db
async def test_audit_approve_finalizes_done(session_factory, company_with_budget):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    await _put_child_auditing(session_factory, child.id)

    ctx = _Ctx()
    async with session_factory() as db:
        ceo_row = await db.get(Agent, ceo.id)
        caller = await db.get(Task, parent.id)  # the CEO's audit task stands in here
        out = await execute_tool(
            db, ctx, agent=ceo_row, task=caller, name="audit_task",
            args={"task_id": str(child.id), "decision": "approve"},
        )
        await db.commit()
    assert not out.is_error and "Approved" in out.observation

    async with session_factory() as db:
        c = await db.get(Task, child.id)
        assert c.status is TaskStatus.done
        assert c.transcript is None  # finalised
    assert ctx.enqueued == []  # approve doesn't re-queue


@requires_db
async def test_audit_reopen_requeues_with_feedback(session_factory, company_with_budget):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    await _put_child_auditing(session_factory, child.id)

    ctx = _Ctx()
    async with session_factory() as db:
        ceo_row = await db.get(Agent, ceo.id)
        caller = await db.get(Task, parent.id)
        out = await execute_tool(
            db, ctx, agent=ceo_row, task=caller, name="audit_task",
            args={
                "task_id": str(child.id),
                "decision": "reopen",
                "comments": "Tighten the ICP and add a concrete channel.",
            },
        )
        await db.commit()
    assert not out.is_error and "Reopened" in out.observation

    async with session_factory() as db:
        c = await db.get(Task, child.id)
        assert c.status is TaskStatus.queued
        assert c.input["audit_feedback"].startswith("Tighten the ICP")
        assert c.input["audit_rounds"] == 1
    assert ctx.enqueued == [child.id]  # the child was re-dispatched


@requires_db
async def test_audit_reopen_requires_comments(session_factory, company_with_budget):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    await _put_child_auditing(session_factory, child.id)

    async with session_factory() as db:
        ceo_row = await db.get(Agent, ceo.id)
        caller = await db.get(Task, parent.id)
        out = await execute_tool(
            db, ctx := _Ctx(), agent=ceo_row, task=caller, name="audit_task",
            args={"task_id": str(child.id), "decision": "reopen"},
        )
    assert out.is_error and "comments" in out.observation.lower()
    assert ctx.enqueued == []


@requires_db
async def test_non_ceo_cannot_audit(session_factory, company_with_budget):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    await _put_child_auditing(session_factory, child.id)
    async with session_factory() as db:
        g = await db.get(Agent, growth.id)
        caller = await db.get(Task, child.id)
        out = await execute_tool(
            db, _Ctx(), agent=g, task=caller, name="audit_task",
            args={"task_id": str(child.id), "decision": "approve"},
        )
    assert out.is_error and "CEO" in out.observation


@requires_db
async def test_audit_rejects_task_not_in_auditing(session_factory, company_with_budget):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    # child is still 'running', not 'auditing'
    async with session_factory() as db:
        ceo_row = await db.get(Agent, ceo.id)
        caller = await db.get(Task, parent.id)
        out = await execute_tool(
            db, _Ctx(), agent=ceo_row, task=caller, name="audit_task",
            args={"task_id": str(child.id), "decision": "approve"},
        )
    assert out.is_error and "isn't awaiting audit" in out.observation


# ── should_review_failure ────────────────────────────────────────────────────
@requires_db
async def test_should_review_failure_for_ceo_dispatched_child(
    session_factory, company_with_budget
):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    async with session_factory() as db:
        g = await db.get(Agent, growth.id)
        c = await db.get(Task, child.id)
        assert await task_svc.should_review_failure(db, agent=g, task=c) is True


@requires_db
async def test_ceo_own_failure_is_not_reviewed(session_factory, company_with_budget):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    async with session_factory() as db:
        c = await db.get(Agent, ceo.id)
        p = await db.get(Task, parent.id)  # CEO's own root task
        assert await task_svc.should_review_failure(db, agent=c, task=p) is False


@requires_db
async def test_retry_cap_stops_review(session_factory, company_with_budget):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    async with session_factory() as db:
        c = await db.get(Task, child.id)
        c.input = {"retry_count": settings.max_task_retries}
        await db.commit()
    async with session_factory() as db:
        g = await db.get(Agent, growth.id)
        c = await db.get(Task, child.id)
        assert await task_svc.should_review_failure(db, agent=g, task=c) is False


# ── begin_failure_review ─────────────────────────────────────────────────────
@requires_db
async def test_begin_failure_review_parks_child_and_spawns_ceo_task(
    session_factory, company_with_budget
):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    async with session_factory() as db:
        review_id = await task_svc.begin_failure_review(
            db, child_id=child.id, output={"error": "TimeoutError: provider timed out"}
        )
        await db.commit()
    assert review_id is not None

    async with session_factory() as db:
        c = await db.get(Task, child.id)
        assert c.status is TaskStatus.auditing
        assert c.input["failure_review"] is True
        assert c.transcript is None  # a retry starts fresh from the goal
        r = await db.get(Task, review_id)
        assert r.agent_id == ceo.id
        assert r.status is TaskStatus.queued
        assert r.input["audit_target_task_id"] == str(child.id)
        assert r.input["audit_target_outcome"] == "failed"
        assert "FAILED" in r.goal and "provider timed out" in r.goal


# ── retry_task: retry / abandon ──────────────────────────────────────────────
async def _put_child_failure_review(session_factory, child_id, *, retry_count=0):
    async with session_factory() as db:
        c = await db.get(Task, child_id)
        c.status = TaskStatus.auditing
        c.output = {"error": "boom"}
        c.input = {**(c.input or {}), "failure_review": True, "retry_count": retry_count}
        await db.commit()


@requires_db
async def test_retry_requeues_and_increments_count(session_factory, company_with_budget):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    await _put_child_failure_review(session_factory, child.id)

    ctx = _Ctx()
    async with session_factory() as db:
        ceo_row = await db.get(Agent, ceo.id)
        caller = await db.get(Task, parent.id)
        out = await execute_tool(
            db, ctx, agent=ceo_row, task=caller, name="retry_task",
            args={"task_id": str(child.id), "decision": "retry", "reason": "looks transient"},
        )
        await db.commit()
    assert not out.is_error and "Re-running" in out.observation

    async with session_factory() as db:
        c = await db.get(Task, child.id)
        assert c.status is TaskStatus.queued
        assert c.input["retry_count"] == 1
        assert "failure_review" not in c.input  # marker cleared for a clean re-run
    assert ctx.enqueued == [child.id]


@requires_db
async def test_abandon_finalizes_failed(session_factory, company_with_budget):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    await _put_child_failure_review(session_factory, child.id)

    ctx = _Ctx()
    async with session_factory() as db:
        ceo_row = await db.get(Agent, ceo.id)
        caller = await db.get(Task, parent.id)
        out = await execute_tool(
            db, ctx, agent=ceo_row, task=caller, name="retry_task",
            args={"task_id": str(child.id), "decision": "abandon", "reason": "missing capability"},
        )
        await db.commit()
    assert not out.is_error and "Abandoned" in out.observation

    async with session_factory() as db:
        c = await db.get(Task, child.id)
        assert c.status is TaskStatus.failed
        assert c.output["abandon_reason"] == "missing capability"
    assert ctx.enqueued == []  # abandon doesn't re-queue


@requires_db
async def test_retry_cap_enforced_in_tool(session_factory, company_with_budget):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    await _put_child_failure_review(
        session_factory, child.id, retry_count=settings.max_task_retries
    )

    ctx = _Ctx()
    async with session_factory() as db:
        ceo_row = await db.get(Agent, ceo.id)
        caller = await db.get(Task, parent.id)
        out = await execute_tool(
            db, ctx, agent=ceo_row, task=caller, name="retry_task",
            args={"task_id": str(child.id), "decision": "retry"},
        )
        await db.commit()
    assert out.is_error and "retries" in out.observation.lower()
    async with session_factory() as db:
        c = await db.get(Task, child.id)
        assert c.status is TaskStatus.failed  # capped → left failed
    assert ctx.enqueued == []


@requires_db
async def test_retry_rejects_non_failure_review(session_factory, company_with_budget):
    """A result audit (auditing without the failure marker) isn't retryable."""
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    await _put_child_auditing(session_factory, child.id)  # no failure_review marker

    async with session_factory() as db:
        ceo_row = await db.get(Agent, ceo.id)
        caller = await db.get(Task, parent.id)
        out = await execute_tool(
            db, _Ctx(), agent=ceo_row, task=caller, name="retry_task",
            args={"task_id": str(child.id), "decision": "retry"},
        )
    assert out.is_error and "isn't awaiting a retry decision" in out.observation


@requires_db
async def test_non_ceo_cannot_retry(session_factory, company_with_budget):
    ceo, growth, parent, child = await _scaffold(session_factory, company_with_budget)
    await _put_child_failure_review(session_factory, child.id)
    async with session_factory() as db:
        g = await db.get(Agent, growth.id)
        caller = await db.get(Task, child.id)
        out = await execute_tool(
            db, _Ctx(), agent=g, task=caller, name="retry_task",
            args={"task_id": str(child.id), "decision": "retry"},
        )
    assert out.is_error and "CEO" in out.observation
