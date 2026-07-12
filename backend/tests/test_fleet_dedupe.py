"""Single-CEO guarantees: no fleet ends up with two CEOs (→ two founder DMs).

Provisioning is idempotent by role (can't create a second CEO), and the
``dedupe_singleton_roles`` helper self-heals any duplicate singleton agents,
cleaning up the orphan DM a removed agent left behind.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import Agent, ChatChannel, ChatParticipant, Company
from app.models.enums import AgentRole, ChatChannelKind
from app.services import chat
from app.services.company_reset import dedupe_singleton_roles
from app.services.onboarding import _fleet_specs, provision_fleet
from tests.conftest import make_company_with_fleet, requires_db


@requires_db
async def test_provision_fleet_is_idempotent_by_role(session_factory, company_with_budget):
    async with session_factory() as db:
        company = await db.get(Company, company_with_budget)
        await provision_fleet(db, company=company, specs=_fleet_specs([]), total_budget_cents=10_000)
        # A second provision must NOT duplicate any singleton role.
        await provision_fleet(db, company=company, specs=_fleet_specs([]), total_budget_cents=10_000)
        await db.commit()

    async with session_factory() as db:
        agents = (
            await db.scalars(select(Agent).where(Agent.company_id == company_with_budget))
        ).all()
    ceos = [a for a in agents if a.role is AgentRole.ceo]
    assert len(ceos) == 1
    roles = [a.role for a in agents]
    assert len(roles) == len(set(roles))  # one agent per role


@requires_db
async def test_dedupe_removes_a_duplicate_ceo_and_cleans_its_orphan_dm(session_factory):
    async with session_factory() as db:
        cid = await make_company_with_fleet(db)
        await db.commit()

    # Inject a second CEO and give it a founder DM — the exact bug (two CEO DMs).
    async with session_factory() as db:
        dup = Agent(company_id=cid, role=AgentRole.ceo, name="CEO Duplicate")
        db.add(dup)
        await db.flush()
        await chat.founder_dm(db, company_id=cid, agent_id=dup.id)
        await db.commit()

    async with session_factory() as db:
        ceos = (
            await db.scalars(
                select(Agent).where(Agent.company_id == cid, Agent.role == AgentRole.ceo)
            )
        ).all()
        assert len(ceos) == 2  # bug reproduced

    # The dedupe helper self-heals it.
    async with session_factory() as db:
        await dedupe_singleton_roles(db, cid)
        await db.commit()

    async with session_factory() as db:
        ceos = (
            await db.scalars(
                select(Agent)
                .where(Agent.company_id == cid, Agent.role == AgentRole.ceo)
                .order_by(Agent.created_at.asc())
            )
        ).all()
        assert len(ceos) == 1
        assert ceos[0].name != "CEO Duplicate"  # the original (oldest) survived

        # The duplicate's founder DM was left with no agent member and swept away.
        directs = (
            await db.scalars(
                select(ChatChannel).where(
                    ChatChannel.company_id == cid,
                    ChatChannel.kind == ChatChannelKind.direct,
                )
            )
        ).all()
        for ch in directs:
            n = await db.scalar(
                select(func.count())
                .select_from(ChatParticipant)
                .where(
                    ChatParticipant.channel_id == ch.id,
                    ChatParticipant.agent_id.is_not(None),
                )
            )
            assert n >= 1  # no orphan direct channel remains
