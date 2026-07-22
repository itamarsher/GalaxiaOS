"""The orphaned-waiting_approval reaper: unblocks a task that parked with nothing
that can ever resume it (no decision, no reply-wait), so the company can't deadlock.

Exercises the ``db``-taking core (``reap_orphaned_approvals_for_company``) against the
fixture session — the same pattern the other scheduled-job tests use — so it runs on the
test's own event loop instead of the app-global ``SessionLocal`` pool.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from app.jobs.scheduled import reap_orphaned_approvals_for_company
from app.models import Agent, AgentRun, Company, DecisionRequest, Task, User
from app.models.enums import (
    AgentRole,
    CompanyStatus,
    DecisionKind,
    DecisionStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from tests.conftest import requires_db

pytestmark = requires_db


async def _task(db, company_id, agent_id, *, status=TaskStatus.waiting_approval):
    run = AgentRun(company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running)
    db.add(run)
    await db.flush()
    run.root_run_id = run.id
    t = Task(
        company_id=company_id,
        run_id=run.id,
        root_run_id=run.id,
        agent_id=agent_id,
        goal="publish the page",
        status=status,
    )
    db.add(t)
    await db.flush()
    return t


@requires_db
async def test_reaper_fails_orphan_but_spares_a_real_decision(session_factory):
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="C", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        agent = Agent(company_id=company.id, role=AgentRole.growth, name="G")
        db.add(agent)
        await db.flush()

        orphan = await _task(db, company.id, agent.id)  # no decision, no wait
        with_decision = await _task(db, company.id, agent.id)  # has a pending decision
        recent_orphan = await _task(db, company.id, agent.id)  # orphan but still in grace
        db.add(
            DecisionRequest(
                company_id=company.id,
                agent_id=agent.id,
                task_id=with_decision.id,
                kind=DecisionKind.spend_approval,
                summary="approve?",
                status=DecisionStatus.pending,
            )
        )
        await db.commit()
        cid, oid, did, rid = company.id, orphan.id, with_decision.id, recent_orphan.id
        # Age the orphan and the has-decision task past the grace window; leave
        # recent_orphan fresh so it's spared for being too new.
        await db.execute(
            text("UPDATE tasks SET updated_at = now() - interval '1 hour' WHERE id in (:a,:b)"),
            {"a": str(oid), "b": str(did)},
        )
        await db.commit()

    async with session_factory() as db:
        reaped = await reap_orphaned_approvals_for_company(db, cid)
        await db.commit()
    assert reaped == 1

    async with session_factory() as db:
        assert (await db.get(Task, oid)).status is TaskStatus.failed  # orphan reaped
        assert (await db.get(Task, did)).status is TaskStatus.waiting_approval  # has a decision
        assert (await db.get(Task, rid)).status is TaskStatus.waiting_approval  # within grace
        assert "Reaped" in (await db.get(Task, oid)).output.get("error", "")
