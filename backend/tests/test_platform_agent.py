"""Platform agent: escalation triggers, issue filing, fleet & dispatch wiring.

The Platform agent is dormant — the CEO never dispatches it. It wakes only when
another agent escalates via `report_bug` / `request_capability`, each of which
spawns a queued task to the Platform agent (reusing the same `_spawn_child`
mechanism the CEO uses). Once awake, it files a tracker issue with `open_issue`.
With no external tracker connected (the default), `open_issue` records the request
to company memory instead of fabricating an external issue, so the escalation loop
still completes offline.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Agent, AgentRun, Task
from app.models.enums import (
    AgentRole,
    MemoryType,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.runtime.tools import TOOL_SPECS, execute_tool
from app.runtime.tools.core import SPECS as CORE_SPECS
from app.services.onboarding import _fleet_specs
from tests.conftest import requires_db


class _FakeCtx:
    """Records enqueued task ids; mirrors the fakes in the other runtime tests."""

    def __init__(self) -> None:
        self.enqueued: list = []

    async def enqueue_task(self, task_id):
        self.enqueued.append(task_id)


async def _make_parent_task(session_factory, company_id, *, with_platform=True):
    async with session_factory() as db:
        # The reporting agent (a functional agent that hit a limitation).
        reporter = Agent(company_id=company_id, role=AgentRole.growth, name="Growth")
        db.add(reporter)
        if with_platform:
            db.add(Agent(company_id=company_id, role=AgentRole.platform, name="Platform"))
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
            agent_id=reporter.id,
            goal="grow signups",
            status=TaskStatus.running,
        )
        db.add(task)
        await db.commit()
        return reporter, task


# ── Triggers spawn a task assigned to the platform agent ──────────────────────


@requires_db
async def test_report_bug_spawns_task_for_platform_agent(session_factory, company_with_budget):
    company_id = company_with_budget
    reporter, task = await _make_parent_task(session_factory, company_id)
    ctx = _FakeCtx()

    async with session_factory() as db:
        outcome = await execute_tool(
            db, ctx, agent=reporter, task=task,
            name="report_bug",
            args={"title": "register_domain crashes", "details": "It 500s on .io"},
        )
        await db.commit()

    # Not terminal / not parked — the reporter carries on with its own task.
    assert outcome.is_error is False
    assert outcome.stop is False
    assert outcome.park is False
    assert len(ctx.enqueued) == 1

    async with session_factory() as db:
        platform = await db.scalar(
            select(Agent).where(
                Agent.company_id == company_id, Agent.role == AgentRole.platform
            )
        )
        child = await db.scalar(
            select(Task).where(Task.parent_task_id == task.id)
        )
    assert child is not None
    assert child.agent_id == platform.id
    assert child.status is TaskStatus.queued
    assert "BUG" in child.goal


@requires_db
async def test_request_capability_spawns_task_for_platform_agent(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    reporter, task = await _make_parent_task(session_factory, company_id)
    ctx = _FakeCtx()

    async with session_factory() as db:
        outcome = await execute_tool(
            db, ctx, agent=reporter, task=task,
            name="request_capability",
            args={"title": "need a Slack tool", "details": "to post launch updates"},
        )
        await db.commit()

    assert outcome.is_error is False
    assert outcome.park is False
    assert len(ctx.enqueued) == 1

    async with session_factory() as db:
        platform = await db.scalar(
            select(Agent).where(
                Agent.company_id == company_id, Agent.role == AgentRole.platform
            )
        )
        child = await db.scalar(select(Task).where(Task.parent_task_id == task.id))
    assert child is not None
    assert child.agent_id == platform.id
    assert "CAPABILITY" in child.goal


@requires_db
async def test_report_bug_without_platform_agent_is_graceful(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    reporter, task = await _make_parent_task(session_factory, company_id, with_platform=False)
    ctx = _FakeCtx()

    async with session_factory() as db:
        outcome = await execute_tool(
            db, ctx, agent=reporter, task=task,
            name="report_bug",
            args={"title": "x", "details": "y"},
        )
        await db.commit()

    assert outcome.is_error is True
    assert "No Platform agent" in outcome.observation
    assert ctx.enqueued == []
    async with session_factory() as db:
        child = await db.scalar(select(Task).where(Task.parent_task_id == task.id))
    assert child is None


# ── open_issue records internally when no external tracker is connected ────────


@requires_db
async def test_open_issue_records_internally_and_writes_memory(
    session_factory, company_with_budget, monkeypatch
):
    company_id = company_with_budget
    # A platform agent on a task is filing the issue.
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.platform, name="Platform")
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
            goal="file an issue",
            status=TaskStatus.running,
        )
        db.add(task)
        await db.commit()

    # The memory table is excluded from the test schema (pgvector), so record the
    # write instead of hitting it — we only need to assert the audit-trail call.
    recorded: list[dict] = []

    async def _fake_write(db, **kwargs):
        recorded.append(kwargs)
        return None

    monkeypatch.setattr("app.services.memory.write", _fake_write)

    async with session_factory() as db:
        outcome = await execute_tool(
            db, object(), agent=agent, task=task,
            name="open_issue",
            args={"title": "Fix .io registration", "body": "stack trace…", "labels": ["bug"]},
        )
        await db.commit()

    # No external tracker connected -> recorded internally, not fabricated.
    assert outcome.is_error is False
    assert "recorded internally" in outcome.observation
    assert "company memory" in outcome.observation
    # Audit trail written to memory.
    assert len(recorded) == 1
    assert recorded[0]["type"] is MemoryType.result
    assert "Fix .io registration" in recorded[0]["title"]


# ── Fleet membership & dispatch isolation ─────────────────────────────────────


def test_platform_agent_in_default_fleet():
    roles = {s["role"] for s in _fleet_specs([])}
    assert "platform" in roles


def test_platform_agent_backfilled_when_omitted():
    roles = {s["role"] for s in _fleet_specs([{"role": "ceo"}, {"role": "growth"}])}
    assert "platform" in roles


def test_platform_not_in_dispatch_task_enum():
    """The CEO's dispatch_task must NOT be able to wake the platform agent."""
    dispatch = next(s for s in CORE_SPECS if s.name == "dispatch_task")
    role_enum = dispatch.input_schema["properties"]["role"]["enum"]
    assert "platform" not in role_enum


def test_platform_tools_available_to_all_agents():
    names = {s.name for s in TOOL_SPECS}
    for expected in ("report_bug", "request_capability", "open_issue"):
        assert expected in names
