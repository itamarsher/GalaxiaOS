"""The orphaned-``auditing`` reaper: fails a task stranded in ``auditing`` when a
worker restart lost the review job, so the company can't deadlock ("cycle active" with
dead tasks). Mirrors the waiting_approval reaper test — exercises the ``db``-taking core
against the fixture session.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from app.jobs.scheduled import reap_orphaned_audits_for_company
from app.models import Agent, AgentRun, Company, Task, User
from app.models.enums import AgentRole, CompanyStatus, RunStatus, RunTrigger, TaskStatus
from tests.conftest import requires_db

pytestmark = requires_db


async def _task(db, company_id, agent_id, *, status):
    run = AgentRun(company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running)
    db.add(run)
    await db.flush()
    run.root_run_id = run.id
    t = Task(
        company_id=company_id,
        run_id=run.id,
        root_run_id=run.id,
        agent_id=agent_id,
        goal="do the thing",
        status=status,
    )
    db.add(t)
    await db.flush()
    return t


@requires_db
async def test_reaper_fails_stranded_audit_but_spares_fresh_and_other_states(session_factory):
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

        stranded = await _task(db, company.id, agent.id, status=TaskStatus.auditing)  # old audit
        fresh = await _task(db, company.id, agent.id, status=TaskStatus.auditing)  # within grace
        running = await _task(db, company.id, agent.id, status=TaskStatus.running)  # not auditing
        await db.commit()
        cid, sid, fid, rid = company.id, stranded.id, fresh.id, running.id
        # Age the stranded audit and the running task past the grace window; leave the
        # fresh audit new so it's spared for being too recent.
        await db.execute(
            text("UPDATE tasks SET updated_at = now() - interval '2 hours' WHERE id in (:a,:b)"),
            {"a": str(sid), "b": str(rid)},
        )
        await db.commit()

    async with session_factory() as db:
        reaped = await reap_orphaned_audits_for_company(db, cid)
        await db.commit()
    assert reaped == 1  # only the old auditing task

    async with session_factory() as db:
        assert (await db.get(Task, sid)).status is TaskStatus.failed  # stranded audit reaped
        assert "Reaped" in (await db.get(Task, sid)).output.get("error", "")
        assert (await db.get(Task, fid)).status is TaskStatus.auditing  # within grace, spared
        assert (await db.get(Task, rid)).status is TaskStatus.running  # other state, untouched
