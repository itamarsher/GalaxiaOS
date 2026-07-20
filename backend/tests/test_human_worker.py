"""Human worker binding — a member staffs a function slot (RFC 0001 step 6).

Drives the user-authenticated human-worker surface end to end (view work → claim →
report) and checks its guards: only human-bound functions are staffable, and a
non-member can't reach the surface. Also checks the orchestrator leaves a
human-backed task offered instead of push-dispatching it.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import main
from app.db import get_db
from app.models import Agent, AgentRun, Company, Membership, Mission, Task, User
from app.models.enums import (
    AgentBackendType,
    AgentRole,
    CompanyStatus,
    MembershipRole,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.security import create_access_token
from tests.conftest import requires_db


def _client() -> TestClient:
    async def _override_db():
        engine = create_async_engine(os.environ["ABOS_TEST_DATABASE_URL"], future=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                yield db
        finally:
            await engine.dispose()

    app = main.create_app()
    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def _auth(uid):
    return {"Authorization": f"Bearer {create_access_token(uid)}"}


@dataclass
class _Ids:
    member_id: uuid.UUID
    outsider_id: uuid.UUID
    company_id: uuid.UUID
    human_agent_id: uuid.UUID
    native_agent_id: uuid.UUID
    task_id: uuid.UUID


async def _seed(session_factory, *, backend=AgentBackendType.human) -> _Ids:
    async with session_factory() as db:
        member = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        outsider = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add_all([member, outsider])
        await db.flush()
        company = Company(owner_user_id=member.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Membership(user_id=member.id, company_id=company.id, role=MembershipRole.founder))
        db.add(Mission(company_id=company.id, raw_text="Grow the thing.", constraints=["No ads"]))
        human = Agent(company_id=company.id, role=AgentRole.growth, name="Growth Lead",
                      backend_type=backend, monthly_budget_cents=5_000)
        native = Agent(company_id=company.id, role=AgentRole.product, name="Product")
        db.add_all([human, native])
        await db.flush()
        run = AgentRun(company_id=company.id, trigger=RunTrigger.scheduled, status=RunStatus.running)
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(company_id=company.id, run_id=run.id, root_run_id=run.id, agent_id=human.id,
                    goal="publish the launch page", status=TaskStatus.queued)
        db.add(task)
        await db.commit()
        return _Ids(member.id, outsider.id, company.id, human.id, native.id, task.id)


@requires_db
async def test_human_worker_full_lifecycle(session_factory):
    ids = await _seed(session_factory)
    with _client() as client:
        base = f"/companies/{ids.company_id}/functions/{ids.human_agent_id}/work"

        # The member sees the function's mandate + the initiative on deck.
        r = client.get(base, headers=_auth(ids.member_id))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["function"] == "growth" and "No ads" in body["mandate"]["constraints"]
        assert body["initiative"]["goal"] == "publish the launch page"

        # Claim it, then report it done.
        r = client.post(f"{base}/claim", headers=_auth(ids.member_id),
                        json={"initiative_id": str(ids.task_id)})
        assert r.status_code == 200 and r.json()["claimed"] is True

        r = client.post(f"{base}/report", headers=_auth(ids.member_id),
                        json={"initiative_id": str(ids.task_id), "outcome": "done", "summary": "live"})
        assert r.status_code == 200 and r.json()["ok"] is True

    async with session_factory() as db:
        assert (await db.get(Task, ids.task_id)).status is TaskStatus.done


@requires_db
async def test_human_worker_guards(session_factory):
    ids = await _seed(session_factory)
    with _client() as client:
        human_base = f"/companies/{ids.company_id}/functions/{ids.human_agent_id}/work"
        native_base = f"/companies/{ids.company_id}/functions/{ids.native_agent_id}/work"

        # A non-member can't reach the surface at all.
        assert client.get(human_base, headers=_auth(ids.outsider_id)).status_code in (403, 404)

        # An agent-staffed (non-human) function isn't a person's to work.
        assert client.get(native_base, headers=_auth(ids.member_id)).status_code == 400


@requires_db
async def test_orchestrator_leaves_human_task_offered(session_factory):
    """A human-backed task must not be push-dispatched — it stays queued to be pulled."""
    from app.runtime import orchestrator
    from app.runtime.context import RuntimeContext

    ids = await _seed(session_factory)
    engine = create_async_engine(os.environ["ABOS_TEST_DATABASE_URL"], future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _noop_enqueue(task_id, *, delay_seconds=0):  # pragma: no cover - unused here
        raise AssertionError("a human-backed task should never be enqueued for a backend run")

    ctx = RuntimeContext(
        session_factory=factory, cost_meter=None, provider=None, enqueue_task=_noop_enqueue
    )
    try:
        result = await orchestrator.run_task(ctx, ids.task_id)
        assert result["status"] == "awaiting_human"
        async with factory() as db:
            assert (await db.get(Task, ids.task_id)).status is TaskStatus.queued
    finally:
        await engine.dispose()
