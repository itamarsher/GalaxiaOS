"""Reset any company to a fresh draft, preserving mission, budget and BYOK keys.

The founder-facing generalisation of the Galaxia dev reset
(:func:`app.services.galaxia.reset_galaxia`): where that rebuilds the fixed
dogfooding company from config, this resets *the caller's own* company. It wipes
the generated org and every operational row (tasks, runs, budget spend, memory,
chat, sites, decisions, …) and re-provisions a clean draft, while the mission,
budget limit, memberships and saved provider keys survive — so the founder can
refine, regenerate, or relaunch without re-entering anything.

Robustness: rather than enumerate every tenant table (which drifts as models are
added), it deletes the company row and lets the ``company_id ON DELETE CASCADE``
on every tenant table wipe the children, then recreates the company under the
same id. This mirrors the proven ``galaxia._reset`` shape.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Budget, Company, Membership, Mission
from app.models.enums import BudgetPeriod, CompanyStatus
from app.observability import get_logger
from app.services.galaxia import (
    _dedupe_singleton_roles,
    _restore_api_keys,
    _snapshot_api_keys,
)
from app.services.onboarding import _fleet_specs, provision_fleet

_log = get_logger("abos.company_reset")


async def reset_company(db: AsyncSession, *, company: Company) -> Company:
    """Wipe a company's generated + operational state and re-provision a draft.

    Snapshots the company's identity, mission, budget, memberships and API keys;
    deletes the company (cascading every tenant row); recreates it under the same
    id as a ``draft``; and provisions the default fleet (no LLM), landing the
    founder at the onboarding plan-approval state — ready to refine/regenerate or
    launch. Saved BYOK keys survive. The caller commits.
    """
    company_id = company.id
    owner_id = company.owner_user_id
    name = company.name

    mission = await db.scalar(select(Mission).where(Mission.company_id == company_id))
    mission_text = mission.raw_text if mission else ""
    constraints = list(mission.constraints or []) if mission else []

    budget = await db.scalar(select(Budget).where(Budget.company_id == company_id))
    budget_cents = budget.limit_cents if budget else 0
    budget_period = budget.period if budget else BudgetPeriod.monthly

    # Preserve every membership (founder + any admins), not just the owner.
    memberships = [
        (m.user_id, m.role)
        for m in (
            await db.scalars(select(Membership).where(Membership.company_id == company_id))
        ).all()
    ]
    saved_keys = await _snapshot_api_keys(db, company_id)

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

    for user_id, role in memberships:
        db.add(Membership(user_id=user_id, company_id=company_id, role=role))
    db.add(
        Budget(company_id=company_id, period=budget_period, limit_cents=budget_cents)
    )
    new_mission = Mission(
        company_id=company_id, raw_text=mission_text, constraints=constraints
    )
    db.add(new_mission)
    await db.flush()
    fresh.mission_id = new_mission.id

    await _restore_api_keys(db, company_id, saved_keys)
    # The default fleet (no LLM) — guarantees a CEO + the oversight roles, wired
    # under the CEO with the monthly budget split by role, exactly like bootstrap.
    await provision_fleet(
        db, company=fresh, specs=_fleet_specs([]), total_budget_cents=budget_cents
    )
    await _dedupe_singleton_roles(db, company_id)
    await db.flush()
    _log.info(
        "Company reset complete (company=%s, keys_preserved=%d)",
        company_id,
        len(saved_keys),
    )
    return fresh
