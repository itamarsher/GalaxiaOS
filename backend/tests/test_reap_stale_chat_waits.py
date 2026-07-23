"""The stale-chat-wait reaper: times out a reply-wait that never got an answer so a
silent founder/teammate can't deadlock a task (and, with it, the business cycle).

Exercises the ``db``-taking core against the fixture session — the same pattern the
other scheduled-job tests use — so it runs on the test's own event loop.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text

from app.jobs.scheduled import reap_stale_chat_waits_for_company
from app.models import Agent, AgentRun, ChatChannel, ChatMessage, ChatWait, Company, Task, User
from app.models.enums import (
    AgentRole,
    ChatChannelKind,
    ChatWaitStatus,
    CompanyStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from tests.conftest import requires_db

pytestmark = requires_db


async def _parked_task_with_wait(db, company_id, agent_id, channel_id):
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
        status=TaskStatus.waiting_approval,
    )
    db.add(t)
    await db.flush()
    wait = ChatWait(
        company_id=company_id,
        channel_id=channel_id,
        task_id=t.id,
        agent_id=agent_id,
        status=ChatWaitStatus.pending,
    )
    db.add(wait)
    await db.flush()
    return t, wait


@requires_db
async def test_reaper_expires_stale_wait_but_spares_a_fresh_one(session_factory):
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
        channel = ChatChannel(
            company_id=company.id, name="agent <-> founder", kind=ChatChannelKind.direct
        )
        db.add(channel)
        await db.flush()

        stale_task, stale_wait = await _parked_task_with_wait(db, company.id, agent.id, channel.id)
        fresh_task, fresh_wait = await _parked_task_with_wait(db, company.id, agent.id, channel.id)
        await db.commit()
        cid = company.id
        stid, swid = stale_task.id, stale_wait.id
        ftid, fwid = fresh_task.id, fresh_wait.id
        # Age only the stale wait past the timeout window.
        await db.execute(
            text("UPDATE chat_waits SET created_at = now() - interval '2 hours' WHERE id = :i"),
            {"i": str(swid)},
        )
        await db.commit()

    async with session_factory() as db:
        woken = await reap_stale_chat_waits_for_company(db, cid)
        await db.commit()
    assert woken == [stid]

    async with session_factory() as db:
        assert (await db.get(ChatWait, swid)).status is ChatWaitStatus.expired  # timed out
        assert (await db.get(Task, stid)).status is TaskStatus.queued  # resumed
        assert (await db.get(ChatWait, fwid)).status is ChatWaitStatus.pending  # still in grace
        assert (await db.get(Task, ftid)).status is TaskStatus.waiting_approval  # left parked
        # A founder-side "no reply" note was posted so the agent knows why it resumed.
        posted = (await db.scalars(select(ChatMessage).where(ChatMessage.company_id == cid))).all()
        assert any("No reply received" in m.body for m in posted)
