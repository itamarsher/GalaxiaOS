"""A billing/quota provider failure must fail the task directly, not park it
in ``auditing`` for a CEO failure review.

The CEO failure-review path is meant for transient failures the CEO can judge
retry-vs-abandon on. A billing rejection (the account/key is out of credit) is
not transient, and the review itself is an LLM call funded by the same
exhausted key — so without this short-circuit, a delegated task would get
stranded in ``auditing`` when the CEO's own review call fails too. See #280.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Agent, AgentRun, Company, Mission, Task, User
from app.models.enums import AgentRole, CompanyStatus, RunStatus, RunTrigger, TaskStatus
from app.providers.base import ProviderError
from app.runtime import orchestrator
from app.runtime.context import RuntimeContext
from tests.conftest import requires_db


class _BillingFailureBackend:
    async def run(self, ctx, agent, task):
        raise ProviderError("out of credit", kind="billing")


@requires_db
async def test_billing_failure_skips_review_and_fails_directly(session_factory, monkeypatch):
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Mission(company_id=company.id, raw_text="Grow.", constraints=[]))
        ceo = Agent(company_id=company.id, role=AgentRole.ceo, name="CEO")
        product = Agent(company_id=company.id, role=AgentRole.product, name="Product")
        db.add_all([ceo, product])
        await db.flush()
        run = AgentRun(company_id=company.id, trigger=RunTrigger.scheduled, status=RunStatus.running)
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        parent_task = Task(
            company_id=company.id, run_id=run.id, root_run_id=run.id, agent_id=ceo.id,
            goal="run the business", status=TaskStatus.running,
        )
        db.add(parent_task)
        await db.flush()
        # A task delegated by the CEO — normally eligible for a CEO failure
        # review (should_review_failure would return True for it).
        task = Task(
            company_id=company.id, run_id=run.id, root_run_id=run.id, agent_id=product.id,
            parent_task_id=parent_task.id, goal="ship it", status=TaskStatus.queued,
        )
        db.add(task)
        await db.commit()
        task_id = task.id

    monkeypatch.setattr(orchestrator, "get_backend", lambda backend_type: _BillingFailureBackend())

    engine = create_async_engine(os.environ["ABOS_TEST_DATABASE_URL"], future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _noop_enqueue(task_id, *, delay_seconds=0):
        raise AssertionError("a billing failure must not enqueue a CEO failure review")

    ctx = RuntimeContext(session_factory=factory, cost_meter=None, provider=None,
                          enqueue_task=_noop_enqueue)
    try:
        with pytest.raises(ProviderError):
            await orchestrator.run_task(ctx, task_id)

        async with factory() as db:
            row = await db.get(Task, task_id)
            assert row.status is TaskStatus.failed
            assert "out of credit" in row.output["error"]
    finally:
        await engine.dispose()
