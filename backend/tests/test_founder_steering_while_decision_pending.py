"""A founder must be able to STEER a DM agent even while a decision is pending.

Regression for the classifier-suppression bug: the ``post_message`` endpoint runs
the founder's reply through the decision-reply classifier first. When the reply
doesn't clearly approve/reject the channel's pending decision (verdict "unclear"),
the endpoint used to swallow the message — no decision resolved *and* no steering
handler spawned — so a live instruction (e.g. "the landing page is too wordy,
redo it") vanished. The fix: spawn the DM handler whenever the reply didn't
RESOLVE a decision, pending-decision or not.

This drives the real HTTP endpoint (``app.api.chat.post_message``) so it guards the
endpoint's composition, not just the underlying services.
"""

from __future__ import annotations

import os
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import main
from app.api import chat as chat_api
from app.db import get_db
from app.models import (
    Agent,
    ChatChannel,
    ChatParticipant,
    Company,
    DecisionRequest,
    Membership,
    Task,
    User,
)
from app.models.enums import (
    AgentRole,
    AgentStatus,
    ChatChannelKind,
    CompanyStatus,
    DecisionKind,
    DecisionStatus,
    MembershipRole,
)
from app.security import create_access_token
from tests.conftest import requires_db

pytestmark = requires_db


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


async def _seed_dm_with_pending_decision(session_factory):
    """Founder ⇄ CEO direct channel that already has a pending structured decision."""
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="C", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(
            Membership(user_id=user.id, company_id=company.id, role=MembershipRole.founder)
        )
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
        db.add(
            ChatParticipant(
                company_id=company.id, channel_id=channel.id, agent_id=agent.id
            )
        )
        db.add(
            DecisionRequest(
                company_id=company.id,
                agent_id=agent.id,
                kind=DecisionKind.plan_approval,
                summary="Approve the Q3 growth plan",
                channel_id=channel.id,
                status=DecisionStatus.pending,
            )
        )
        await db.commit()
        return user.id, company.id, agent.id, channel.id


@requires_db
async def test_steering_dm_spawns_handler_even_with_pending_decision(
    session_factory, monkeypatch
):
    uid, cid, aid, chid = await _seed_dm_with_pending_decision(session_factory)

    # The endpoint enqueues the spawned handler onto Redis (unavailable in tests);
    # we only assert the DB row was created, so make the enqueue a no-op.
    async def _noop_enqueue(_task_id):
        return None

    monkeypatch.setattr(chat_api, "enqueue_task", _noop_enqueue)

    with _client() as client:
        # A steering message that neither approves nor rejects the pending decision.
        # With no LLM provider configured the classifier degrades to "unclear", so
        # the decision stays pending — the message must NOT be swallowed.
        r = client.post(
            f"/companies/{cid}/chat/channels/{chid}/messages",
            headers=_auth(uid),
            json={"message": "The landing page is too wordy — please redo it, tighter copy."},
        )
        assert r.status_code == 200, r.text

    async with session_factory() as db:
        # The decision is still pending (the reply didn't resolve it)...
        dec = await db.scalar(
            select(DecisionRequest).where(DecisionRequest.channel_id == chid)
        )
        assert dec is not None and dec.status == DecisionStatus.pending
        # ...and a DM handler task was spawned so the CEO reads and acts on the steer.
        handler = await db.scalar(
            select(Task).where(
                Task.company_id == cid,
                Task.agent_id == aid,
                Task.input["founder_dm_channel_id"].astext == str(chid),
            )
        )
        assert handler is not None  # would be None under the old swallowing behaviour
