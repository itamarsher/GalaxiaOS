"""A job cancelled mid-flight (arq job-timeout) must not orphan its task.

``asyncio.CancelledError`` is a ``BaseException``, not caught by a bare
``except Exception`` — so before this fix, a task cancelled by arq's
job-timeout stayed stuck in ``running`` forever (only a worker restart's
``recover_pending_work`` would ever rescue it). See issue #272.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Agent, AgentRun, Company, Mission, Task, User
from app.models.enums import AgentRole, CompanyStatus, RunStatus, RunTrigger, TaskStatus
from app.runtime import orchestrator
from app.runtime.context import RuntimeContext
from tests.conftest import requires_db


class _CancellingBackend:
    async def run(self, ctx, agent, task):
        raise asyncio.CancelledError()


@requires_db
async def test_cancelled_task_is_marked_failed_not_left_running(session_factory, monkeypatch):
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Mission(company_id=company.id, raw_text="Grow.", constraints=[]))
        agent = Agent(company_id=company.id, role=AgentRole.product, name="Product")
        db.add(agent)
        await db.flush()
        run = AgentRun(company_id=company.id, trigger=RunTrigger.scheduled, status=RunStatus.running)
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company.id, run_id=run.id, root_run_id=run.id, agent_id=agent.id,
            goal="ship it", status=TaskStatus.queued,
        )
        db.add(task)
        await db.commit()
        task_id = task.id

    monkeypatch.setattr(orchestrator, "get_backend", lambda backend_type: _CancellingBackend())

    engine = create_async_engine(os.environ["ABOS_TEST_DATABASE_URL"], future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _noop_enqueue(task_id, *, delay_seconds=0):  # pragma: no cover - unused here
        raise AssertionError("a root task's cancellation has no CEO to review it")

    ctx = RuntimeContext(session_factory=factory, cost_meter=None, provider=None,
                          enqueue_task=_noop_enqueue)
    try:
        with pytest.raises(asyncio.CancelledError):
            await orchestrator.run_task(ctx, task_id)

        async with factory() as db:
            row = await db.get(Task, task_id)
            assert row.status is TaskStatus.failed
            assert "CancelledError" in row.output["error"]
    finally:
        await engine.dispose()
