"""Galaxia bootstrap — the dogfooding company ABOS runs on itself.

Galaxia is the reference business whose mission is to build and operate ABOS.
Its agents' unmet needs feed the shared feature-request backlog, and its Platform
agent is the ONLY actor authorized to promote that backlog into real tracker
issues on this repo (see :mod:`app.runtime.tools.platform`). Because promotion
authority is keyed to a specific founder-user membership
(``settings.galaxia_founder_user_id``), that company must actually exist in every
deployment — otherwise the entire demand→issue loop has no origin and never runs.
This module provisions it deterministically and idempotently at startup.

Idempotency & concurrency: the founder user and company use deterministic ids
derived from config, and provisioning runs under a Postgres advisory lock inside
one transaction, so the API and an in-process worker booting together can't create
it twice. A later boot (or a second process) sees the company already exists and
returns without touching anything.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import Budget, Company, Membership, Mission, Policy, User
from app.models.enums import (
    BudgetPeriod,
    CompanyStatus,
    MembershipRole,
    PolicyEffect,
    PolicyScope,
)
from app.observability import get_logger
from app.security import hash_password
from app.services import chat as chat_svc
from app.services import governance as gov
from app.services.onboarding import _fleet_specs, provision_fleet

_log = get_logger("abos.galaxia")

# A stable advisory-lock key so concurrent boots serialize on the bootstrap rather
# than racing to insert the same fixed-id rows. Arbitrary constant ("galaxia").
_BOOTSTRAP_LOCK_KEY = 0x6A1AC71A


def galaxia_founder_user_id() -> uuid.UUID:
    """The fixed founder-user id that gates the Platform promoter tools."""
    return uuid.UUID(str(settings.galaxia_founder_user_id))


def galaxia_company_id() -> uuid.UUID:
    """The Galaxia company id — configured, or derived deterministically.

    When ``galaxia_company_id`` is unset we derive a stable uuid5 from the founder
    id, so there is no magic literal to keep in sync yet the id never changes
    across restarts (which is what makes the bootstrap idempotent).
    """
    configured = str(settings.galaxia_company_id).strip()
    if configured:
        return uuid.UUID(configured)
    return uuid.uuid5(uuid.NAMESPACE_URL, f"galaxia:{settings.galaxia_founder_user_id}")


async def ensure_bootstrap() -> uuid.UUID | None:
    """Provision the Galaxia company if it doesn't exist yet. Idempotent.

    Returns the Galaxia company id (whether newly created or pre-existing), or
    ``None`` when bootstrapping is disabled or fails. A bootstrap failure is logged
    and swallowed — it must never stop the app from serving requests.
    """
    if not settings.galaxia_bootstrap_enabled:
        return None
    try:
        async with SessionLocal() as db:
            company_id = await _bootstrap(db)
            await db.commit()
            return company_id
    except Exception:  # noqa: BLE001 - bootstrap must never crash app startup
        _log.exception("Galaxia bootstrap failed")
        return None


async def _bootstrap(db: AsyncSession) -> uuid.UUID:
    """Create the Galaxia founder, company, fleet, and governance. Idempotent."""
    # Serialize concurrent boots (API + in-process worker) so they can't both try
    # to insert the fixed-id rows.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k)"), {"k": _BOOTSTRAP_LOCK_KEY}
    )

    company_id = galaxia_company_id()
    if await db.get(Company, company_id) is not None:
        return company_id  # already bootstrapped — nothing to do

    user = await _ensure_founder(db)
    company = Company(
        id=company_id,
        owner_user_id=user.id,
        name=settings.galaxia_company_name,
        status=CompanyStatus.draft,
    )
    db.add(company)
    await db.flush()

    db.add(
        Membership(
            user_id=user.id, company_id=company.id, role=MembershipRole.founder
        )
    )
    db.add(
        Budget(
            company_id=company.id,
            period=BudgetPeriod.monthly,
            limit_cents=settings.galaxia_monthly_budget_cents,
        )
    )
    mission = Mission(
        company_id=company.id, raw_text=settings.galaxia_mission, constraints=[]
    )
    db.add(mission)
    await db.flush()
    company.mission_id = mission.id

    # Deterministic fleet — no LLM call. ``_fleet_specs([])`` yields the full
    # default fleet, which guarantees the Platform agent (the promoter) among the
    # oversight roles, wired under the CEO with the budget split by role.
    await provision_fleet(
        db,
        company=company,
        specs=_fleet_specs([]),
        total_budget_cents=settings.galaxia_monthly_budget_cents,
    )

    # Seed governance and activate, mirroring onboarding.launch — but WITHOUT
    # kicking a launch run here: the business-cycle cron picks up active companies,
    # so Galaxia starts operating on the next tick without enqueuing work at boot.
    for spec in gov.default_policies():
        db.add(
            Policy(
                company_id=company.id,
                name=spec["name"],
                scope=PolicyScope(spec["scope"]),
                rule=spec["rule"],
                effect=PolicyEffect(spec["effect"]),
                priority=spec["priority"],
            )
        )
    await gov.set_external_comms_approval(db, company_id=company.id, enabled=False)
    await chat_svc.ensure_ceo_dm(db, company_id=company.id)
    company.status = CompanyStatus.active
    await db.flush()

    _log.info("Galaxia bootstrap complete (company=%s)", company_id)
    return company_id


async def _ensure_founder(db: AsyncSession) -> User:
    """Get-or-create the Galaxia founder with the fixed promoter-gate id.

    The user MUST carry :func:`galaxia_founder_user_id` — the Platform promoter
    gate authorizes by that exact id's membership, so we never substitute an
    existing account with a different id. If the configured email is already taken
    by another account, the insert fails the unique constraint and the whole
    bootstrap is logged and skipped (an operator misconfiguration), which is
    correct: silently binding the gate to the wrong id would be worse.
    """
    user_id = galaxia_founder_user_id()
    existing = await db.get(User, user_id)
    if existing is not None:
        return existing
    user = User(
        id=user_id,
        email=settings.galaxia_founder_email,
        # A random, unusable password: this is a system-owned account, not a
        # password login. The founder operates Galaxia through the app.
        hashed_password=hash_password(uuid.uuid4().hex),
    )
    db.add(user)
    await db.flush()
    return user
