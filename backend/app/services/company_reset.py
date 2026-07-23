"""Reset any company to a fresh draft, preserving mission, budget and BYOK keys.

Resets *the caller's own* company: it wipes the generated org and every
operational row (tasks, runs, budget spend, memory, chat, sites, decisions, …)
and re-provisions a clean draft, while the mission, budget limit, memberships and
saved provider keys survive — so the founder can refine, regenerate, or relaunch
without re-entering anything.

Robustness: rather than enumerate every tenant table (which drifts as models are
added), it deletes the company row and lets the ``company_id ON DELETE CASCADE``
on every tenant table wipe the children, then recreates the company under the
same id.

This module also owns the fleet-hygiene helpers (API-key snapshot/restore across a
cascade delete, and singleton-role de-duplication) that used to live in the
now-removed Galaxia bootstrap module.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Agent,
    ApiKey,
    Budget,
    ChatChannel,
    ChatParticipant,
    Company,
    Membership,
    Mission,
)
from app.models.enums import (
    AgentRole,
    ApiKeyStatus,
    BudgetPeriod,
    ChatChannelKind,
    CompanyStatus,
)
from app.observability import get_logger
from app.services.onboarding import _fleet_specs, provision_fleet

_log = get_logger("abos.company_reset")


# ── API-key snapshot/restore across a cascade delete ──────────────────────────


async def snapshot_api_keys(db: AsyncSession, company_id: uuid.UUID) -> list[dict]:
    """Capture the company's BYOK key rows as plain dicts (survives the delete).

    The envelope ciphertext is self-contained (DEK wrapped by the master key), so a
    key re-inserted under the same company id decrypts exactly as before.
    """
    keys = (
        await db.scalars(select(ApiKey).where(ApiKey.company_id == company_id))
    ).all()
    return [
        {
            "provider": k.provider,
            "encrypted_key": k.encrypted_key,
            "encrypted_data_key": k.encrypted_data_key,
            "nonce": k.nonce,
            "key_fingerprint": k.key_fingerprint,
            "status": k.status,
        }
        for k in keys
    ]


async def restore_api_keys(
    db: AsyncSession, company_id: uuid.UUID, saved: list[dict]
) -> None:
    """Re-insert snapshotted key rows under the (recreated) company."""
    for k in saved:
        db.add(
            ApiKey(
                company_id=company_id,
                provider=k["provider"],
                encrypted_key=k["encrypted_key"],
                encrypted_data_key=k["encrypted_data_key"],
                nonce=k["nonce"],
                key_fingerprint=k["key_fingerprint"],
                status=k.get("status") or ApiKeyStatus.active,
            )
        )
    if saved:
        await db.flush()


# ── singleton-role de-duplication ─────────────────────────────────────────────

# Roles that must be a singleton in a fleet — exactly one per company. The CEO is
# the root planner; the rest are the guaranteed oversight roles. Duplicates of any
# of these are spurious (e.g. two CEOs surface as two founder DMs).
_SINGLETON_ROLES = (
    AgentRole.ceo,
    AgentRole.governance,
    AgentRole.auditor,
    AgentRole.data,
    AgentRole.platform,
)


async def dedupe_singleton_roles(db: AsyncSession, company_id: uuid.UUID) -> int:
    """Collapse any duplicate singleton-role agents, keeping the oldest of each.

    Guards against a fleet that ended up with, e.g., two CEOs (which the UI renders
    as two founder↔CEO DMs). Keeps the earliest-created agent for each singleton
    role and deletes the extras; deleting an agent cascades its participant rows, so
    afterwards we sweep any direct channel left with no agent member.
    """
    removed = 0
    for role in _SINGLETON_ROLES:
        agents = (
            await db.scalars(
                select(Agent)
                .where(Agent.company_id == company_id, Agent.role == role)
                .order_by(Agent.created_at.asc(), Agent.id.asc())
            )
        ).all()
        for extra in agents[1:]:
            await db.delete(extra)
            removed += 1
    if removed:
        await db.flush()
        await _delete_orphan_direct_channels(db, company_id)
        _log.info(
            "Dedupe removed %d duplicate singleton agent(s) (company=%s)",
            removed,
            company_id,
        )
    return removed


async def _delete_orphan_direct_channels(db: AsyncSession, company_id: uuid.UUID) -> None:
    """Delete direct (DM) channels left with no agent participant after a dedupe.

    When a duplicate agent is removed, its 1:1 DM with the founder loses its only
    agent member; such an orphan would otherwise linger as an empty thread.
    """
    channels = (
        await db.scalars(
            select(ChatChannel).where(
                ChatChannel.company_id == company_id,
                ChatChannel.kind == ChatChannelKind.direct,
            )
        )
    ).all()
    for ch in channels:
        agent_members = await db.scalar(
            select(func.count())
            .select_from(ChatParticipant)
            .where(
                ChatParticipant.channel_id == ch.id,
                ChatParticipant.agent_id.is_not(None),
            )
        )
        if not agent_members:
            await db.delete(ch)
    await db.flush()


# ── the founder-facing company reset ──────────────────────────────────────────


async def reset_company(
    db: AsyncSession,
    *,
    company: Company,
    mission_text: str | None = None,
    constraints: list[str] | None = None,
) -> Company:
    """Wipe a company's generated + operational state and re-provision a draft.

    Snapshots the company's identity, mission, budget, memberships and API keys;
    deletes the company (cascading every tenant row); recreates it under the same
    id as a ``draft``; and provisions the default fleet (no LLM), landing the
    founder at the onboarding plan-approval state — ready to refine/regenerate or
    launch. Saved BYOK keys survive. The caller commits.

    The founder may **edit the mission as part of the reset**: pass ``mission_text``
    and/or ``constraints`` to relaunch with a revised mission instead of the current
    one. Either left as ``None`` keeps the existing value (so an unchanged field is
    preserved, not blanked); an empty ``constraints`` list explicitly clears them.
    A revised ``mission_text`` drops the previously detected language/summary so the
    next generation re-derives them from the new text.
    """
    company_id = company.id
    owner_id = company.owner_user_id
    name = company.name

    mission = await db.scalar(select(Mission).where(Mission.company_id == company_id))
    existing_text = mission.raw_text if mission else ""
    existing_constraints = list(mission.constraints or []) if mission else []
    # Edited mission wins when supplied; otherwise preserve what was there.
    edited_text = mission_text.strip() if mission_text is not None else None
    mission_text = edited_text if edited_text else existing_text
    constraints = constraints if constraints is not None else existing_constraints

    budget = await db.scalar(select(Budget).where(Budget.company_id == company_id))
    budget_cents = budget.limit_cents if budget else 0
    budget_period = budget.period if budget else BudgetPeriod.monthly

    # Preserve every membership (founder + any admins), not just the owner — and
    # crucially its *configuration*, not just (user, role). A member's involvement
    # (which the involvement router uses to decide what escalates to a human vs.
    # auto-approves), their pending proposed_involvement, data-access labels, and
    # coverage all have to survive the cascade delete. Dropping ``involvement`` here
    # silently disarmed the founder's approval gates after a reset: with no opt-in on
    # record the router auto-approved plans/hires/spend that should have escalated.
    memberships = [
        {
            "user_id": m.user_id,
            "role": m.role,
            "involvement": m.involvement,
            "proposed_involvement": m.proposed_involvement,
            "access_labels": m.access_labels,
            "coverage": m.coverage,
        }
        for m in (
            await db.scalars(select(Membership).where(Membership.company_id == company_id))
        ).all()
    ]
    saved_keys = await snapshot_api_keys(db, company_id)

    # Cascade-delete every tenant row, then rebuild a pristine draft.
    await db.delete(company)
    await db.flush()

    fresh = Company(
        id=company_id,
        owner_user_id=owner_id,
        name=name,
        status=CompanyStatus.draft,
    )
    db.add(fresh)
    await db.flush()

    for m in memberships:
        db.add(
            Membership(
                company_id=company_id,
                user_id=m["user_id"],
                role=m["role"],
                involvement=m["involvement"],
                proposed_involvement=m["proposed_involvement"],
                access_labels=m["access_labels"],
                coverage=m["coverage"],
            )
        )
    db.add(
        Budget(company_id=company_id, period=budget_period, limit_cents=budget_cents)
    )
    new_mission = Mission(
        company_id=company_id, raw_text=mission_text, constraints=constraints
    )
    db.add(new_mission)
    await db.flush()
    fresh.mission_id = new_mission.id

    await restore_api_keys(db, company_id, saved_keys)
    # The default fleet (no LLM) — guarantees a CEO + the oversight roles, wired
    # under the CEO with the monthly budget split by role.
    await provision_fleet(
        db, company=fresh, specs=_fleet_specs([]), total_budget_cents=budget_cents
    )
    await dedupe_singleton_roles(db, company_id)
    await db.flush()
    _log.info(
        "Company reset complete (company=%s, keys_preserved=%d)",
        company_id,
        len(saved_keys),
    )
    return fresh
