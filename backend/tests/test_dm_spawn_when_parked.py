"""A founder DM must not be silently dropped when the agent has a PARKED task.

``spawn_dm_handler_task`` coalesces a new founder message into an already-open DM
handler so a burst doesn't pile up duplicates — but a handler parked in
``waiting_approval`` (blocked on a decision) will never read the message, so
coalescing into it drops the founder's message. The fix: only coalesce into a
handler that's still actively reading (queued/running/auditing); when the only open
handler is parked, spawn a fresh one so the founder can always steer.
"""

from __future__ import annotations

import uuid

from app.models import Agent, AgentRun, ChatChannel, Company, Task, User
from app.models.enums import (
    AgentRole,
    AgentStatus,
    ChatChannelKind,
    CompanyStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.services.chat import spawn_dm_handler_task
from tests.conftest import requires_db

pytestmark = requires_db


async def _setup(session_factory):
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="C", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        agent = Agent(
            company_id=company.id, role=AgentRole.ceo, name="CEO", status=AgentStatus.active
        )
        db.add(agent)
        await db.flush()
        channel = ChatChannel(
            company_id=company.id, name="ceo <-> founder", kind=ChatChannelKind.direct
        )
        db.add(channel)
        await db.flush()
        await db.commit()
        return company.id, agent.id, channel.id


async def _dm_task(db, company_id, agent_id, channel_id, status):
    run = AgentRun(company_id=company_id, trigger=RunTrigger.founder_command, status=RunStatus.running)
    db.add(run)
    await db.flush()
    run.root_run_id = run.id
    t = Task(
        company_id=company_id,
        run_id=run.id,
        root_run_id=run.id,
        agent_id=agent_id,
        goal="handle the founder DM",
        input={"founder_dm_channel_id": str(channel_id)},
        status=status,
    )
    db.add(t)
    await db.flush()
    return t


@requires_db
async def test_parked_dm_task_does_not_block_a_new_founder_message(session_factory):
    cid, aid, chid = await _setup(session_factory)
    async with session_factory() as db:
        channel = await db.get(ChatChannel, chid)
        # A handler parked in waiting_approval (blocked on a decision) — must NOT swallow.
        await _dm_task(db, cid, aid, chid, TaskStatus.waiting_approval)
        await db.commit()
        spawned = await spawn_dm_handler_task(
            db, company_id=cid, channel=channel, agent_id=aid, founder_message="new steer"
        )
        await db.commit()
    assert spawned is not None  # a fresh handler was created despite the parked task


@requires_db
async def test_running_dm_task_still_coalesces(session_factory):
    cid, aid, chid = await _setup(session_factory)
    async with session_factory() as db:
        channel = await db.get(ChatChannel, chid)
        # A handler that's actively running WILL read the message → coalesce (no duplicate).
        await _dm_task(db, cid, aid, chid, TaskStatus.running)
        await db.commit()
        spawned = await spawn_dm_handler_task(
            db, company_id=cid, channel=channel, agent_id=aid, founder_message="another"
        )
        await db.commit()
    assert spawned is None
