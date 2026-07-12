"""The platform company's reliability monitor: failed task → Platform investigation.

Deterministic half of the loop: a failed task on the platform company is picked up
exactly once and turned into a Platform-agent investigation task (which then reads
code / Render and files report_bug). The agent's investigation itself is
prompt-driven and not asserted here.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Agent, AgentRun, Task
from app.models.enums import AgentRole, RunStatus, RunTrigger, TaskStatus
from app.services import reliability
from tests.conftest import make_company_with_fleet, requires_db


async def _failed_task(db, company_id, agent_id, *, goal="grow signups") -> Task:
    run = AgentRun(company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running)
    db.add(run)
    await db.flush()
    run.root_run_id = run.id
    task = Task(
        company_id=company_id,
        run_id=run.id,
        root_run_id=run.id,
        agent_id=agent_id,
        goal=goal,
        status=TaskStatus.failed,
        output={"error": "boom: KeyError 'x'"},
    )
    db.add(task)
    await db.flush()
    return task


@requires_db
async def test_failed_task_becomes_a_platform_investigation_once(session_factory):
    async with session_factory() as db:
        cid = await make_company_with_fleet(db)
        await db.commit()

    async with session_factory() as db:
        growth = await db.scalar(
            select(Agent).where(Agent.company_id == cid, Agent.role == AgentRole.growth)
        )
        ft = await _failed_task(db, cid, growth.id)
        await db.commit()
        ft_id = ft.id

    async with session_factory() as db:
        result = await reliability.review_failed_tasks(db, company_id=cid, limit=5)
        await db.commit()
    assert result["reviewed"] == 1
    assert len(result["review_task_ids"]) == 1

    async with session_factory() as db:
        # The original failure is marked reviewed.
        ft = await db.get(Task, ft_id)
        assert ft.reliability_reviewed_at is not None

        # A Platform-agent investigation task was created for it.
        platform = await db.scalar(
            select(Agent).where(Agent.company_id == cid, Agent.role == AgentRole.platform)
        )
        review = await db.scalar(
            select(Task).where(Task.company_id == cid, Task.agent_id == platform.id)
        )
        assert review is not None
        assert review.status is TaskStatus.queued
        assert review.input["reliability_review"]["failed_task_id"] == str(ft_id)
        # Pre-stamped so the monitor never investigates its own investigation.
        assert review.reliability_reviewed_at is not None
        # The failure's error is carried into the investigation goal.
        assert "KeyError" in review.goal

    # A second pass finds nothing new (already reviewed).
    async with session_factory() as db:
        result2 = await reliability.review_failed_tasks(db, company_id=cid, limit=5)
        await db.commit()
    assert result2["reviewed"] == 0


@requires_db
async def test_only_failed_tasks_are_reviewed(session_factory):
    async with session_factory() as db:
        cid = await make_company_with_fleet(db)
        await db.commit()

    async with session_factory() as db:
        growth = await db.scalar(
            select(Agent).where(Agent.company_id == cid, Agent.role == AgentRole.growth)
        )
        # A completed (non-failed) task must be ignored.
        run = AgentRun(company_id=cid, trigger=RunTrigger.scheduled, status=RunStatus.running)
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        done = Task(
            company_id=cid, run_id=run.id, root_run_id=run.id, agent_id=growth.id,
            goal="ok", status=TaskStatus.done, output={"result": "fine"},
        )
        db.add(done)
        await db.commit()

    async with session_factory() as db:
        result = await reliability.review_failed_tasks(db, company_id=cid, limit=5)
        await db.commit()
    assert result["reviewed"] == 0
