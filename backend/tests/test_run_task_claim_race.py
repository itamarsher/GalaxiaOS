"""Two concurrent ``run_task`` calls for the same task must dispatch at most once.

Before this fix, the queued/waiting_approval -> running transition in
``run_task`` was a plain read-then-write with no row lock, so two concurrent
invocations (a redelivered arq job, or ``enqueue_task`` firing twice) could
both read ``status == queued`` before either committed, and both dispatch the
backend. For a CEO-delegated task this created two audit tasks for the same
child result, and once the CEO resolved the first, ``audit_task`` on the
second (stale) audit task failed with "not awaiting audit (it's queued)".
See issue #362.
"""

from __future__ import annotations

import asyncio
import os
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Agent, AgentRun, Company, Mission, Task, User
from app.models.enums import AgentRole, CompanyStatus, RunStatus, RunTrigger, TaskStatus
from app.runtime import orchestrator
from app.runtime.context import RuntimeContext
from tests.conftest import requires_db


class _CountingBackend:
    def __init__(self):
        self.calls = 0

    async def run(self, ctx, agent, task):
        self.calls += 1
        raise RuntimeError("boom")


@requires_db
async def test_concurrent_run_task_dispatches_backend_once(session_factory, monkeypatch):
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
        run = AgentRun(
            company_id=company.id, trigger=RunTrigger.scheduled, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company.id,
            run_id=run.id,
            root_run_id=run.id,
            agent_id=agent.id,
            goal="ship it",
            status=TaskStatus.queued,
        )
        db.add(task)
        await db.commit()
        task_id = task.id

    backend = _CountingBackend()
    monkeypatch.setattr(orchestrator, "get_backend", lambda backend_type: backend)

    engine = create_async_engine(os.environ["ABOS_TEST_DATABASE_URL"], future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _noop_enqueue(task_id, *, delay_seconds=0):  # pragma: no cover - unused here
        pass

    ctx = RuntimeContext(
        session_factory=factory, cost_meter=None, provider=None, enqueue_task=_noop_enqueue
    )
    try:
        results = await asyncio.gather(
            orchestrator.run_task(ctx, task_id),
            orchestrator.run_task(ctx, task_id),
            return_exceptions=True,
        )
        assert backend.calls == 1, "both concurrent run_task calls dispatched the backend"

        skipped = [r for r in results if isinstance(r, dict) and r["status"].startswith("skipped:")]
        assert len(skipped) == 1

        async with factory() as db:
            row = await db.get(Task, task_id)
            assert row.status is TaskStatus.failed
    finally:
        await engine.dispose()
