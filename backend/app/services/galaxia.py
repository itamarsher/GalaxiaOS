"""Galaxia bootstrap — the dogfooding company GalaxiaOS runs on itself.

Galaxia is the reference business whose mission is to build and operate GalaxiaOS.
Its agents' unmet needs feed the shared feature-request backlog, and its Platform
agent is the ONLY actor authorized to promote that backlog into real tracker
issues on this repo (see :mod:`app.runtime.tools.platform`). Because promotion
authority is keyed to a specific founder-user membership
(``settings.galaxia_founder_user_id``), that company must actually exist in every
deployment — otherwise the entire demand→issue loop has no origin and never runs.
This module provisions it deterministically and idempotently at startup.

Three entry points:

- :func:`ensure_bootstrap` — provision Galaxia if absent; otherwise reconcile the
  stored mission to config (so the mission in config is the source of truth even
  for an already-provisioned Galaxia), or fully re-provision when
  ``galaxia_reset_on_boot`` is set.
- :func:`reset_galaxia` — while the product is under heavy development, wipe
  Galaxia's generated state and re-provision from fleet creation, **preserving
  saved BYOK keys** (so you don't re-enter the model key every time). Backs the
  ``POST /dev/galaxia/reset`` endpoint.

Idempotency & concurrency: the founder user and company use deterministic ids
derived from config, and every entry runs under a Postgres advisory lock inside
one transaction, so the API and an in-process worker booting together can't race.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import ApiKey, Budget, Company, Membership, Mission, User
from app.models.enums import (
    ApiKeyStatus,
    BudgetPeriod,
    CompanyStatus,
    MembershipRole,
)
from app.observability import get_logger
from app.security import hash_password
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


async def _lock(db: AsyncSession) -> None:
    """Serialize Galaxia provisioning on one advisory lock (released at commit)."""
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _BOOTSTRAP_LOCK_KEY})


async def ensure_bootstrap() -> uuid.UUID | None:
    """Provision Galaxia if absent; else reconcile its mission (or reset on boot).

    Returns the Galaxia company id, or ``None`` when bootstrapping is disabled or
    fails. A failure is logged and swallowed — it must never stop the app serving.
    """
    if not settings.galaxia_bootstrap_enabled:
        return None
    try:
        async with SessionLocal() as db:
            company_id = await _run(db)
            await db.commit()
            return company_id
    except Exception:  # noqa: BLE001 - bootstrap must never crash app startup
        _log.exception("Galaxia bootstrap failed")
        return None


async def _run(db: AsyncSession) -> uuid.UUID:
    """Provision-if-absent, else reset-on-boot, else reconcile the mission."""
    await _lock(db)
    company_id = galaxia_company_id()
    existing = await db.get(Company, company_id)
    if existing is None:
        company = await _ensure_company(db)
        await _provision_operating_state(db, company)
        _log.info("Galaxia bootstrap complete (company=%s)", company_id)
    elif settings.galaxia_reset_on_boot:
        _log.warning(
            "galaxia_reset_on_boot set — re-provisioning Galaxia from fleet creation"
        )
        await _reset(db)
    else:
        await _reconcile_mission(db, existing)
    return company_id


async def reset_galaxia(db: AsyncSession) -> uuid.UUID:
    """Wipe Galaxia's generated state and re-provision, preserving BYOK keys.

    The caller commits. Deletes the company (cascading all of its tenant rows)
    after snapshotting its API keys, then recreates the company under the same
    fixed id and restores the keys — so the fleet, mission, objectives, runs, and
    memory are rebuilt fresh while saved provider keys survive.
    """
    await _lock(db)
    return await _reset(db)


async def _reset(db: AsyncSession) -> uuid.UUID:
    company_id = galaxia_company_id()
    saved_keys = await _snapshot_api_keys(db, company_id)
    existing = await db.get(Company, company_id)
    if existing is not None:
        # Cascade wipes every tenant row (fleet, mission, runs, memory, and the
        # api_keys we just snapshotted); we re-insert the keys below.
        await db.delete(existing)
        await db.flush()
    company = await _ensure_company(db)
    await _restore_api_keys(db, company_id, saved_keys)
    await _provision_operating_state(db, company)
    _log.info(
        "Galaxia reset complete (company=%s, keys_preserved=%d)",
        company_id,
        len(saved_keys),
    )
    return company_id


# ── building blocks ───────────────────────────────────────────────────────────


async def _ensure_company(db: AsyncSession) -> Company:
    """Ensure the founder, company (draft), membership, and budget exist."""
    user = await _ensure_founder(db)
    company_id = galaxia_company_id()
    company = await db.get(Company, company_id)
    if company is None:
        company = Company(
            id=company_id,
            owner_user_id=user.id,
            name=settings.galaxia_company_name,
            status=CompanyStatus.draft,
        )
        db.add(company)
        await db.flush()

    membership = await db.scalar(
        select(Membership).where(
            Membership.company_id == company_id, Membership.user_id == user.id
        )
    )
    if membership is None:
        db.add(
            Membership(user_id=user.id, company_id=company_id, role=MembershipRole.founder)
        )
    if await db.scalar(select(Budget).where(Budget.company_id == company_id)) is None:
        db.add(
            Budget(
                company_id=company_id,
                period=BudgetPeriod.monthly,
                limit_cents=settings.galaxia_monthly_budget_cents,
            )
        )
    await db.flush()
    return company


async def _provision_operating_state(db: AsyncSession, company: Company) -> None:
    """Generate the (draft) org plan and stop at the onboarding approval phase.

    Lands the company exactly where a founder is after generation but before
    launch: **status stays ``draft``** with a generated fleet (the plan to
    approve). It does NOT seed governance, open the CEO DM, or kick a launch run —
    those are the founder's *launch* action (``onboarding.launch`` via
    ``POST /onboarding/{id}/launch``), i.e. approving the plan. This keeps even the
    dogfooding company inside the normal onboarding flow instead of springing to
    life pre-approved.

    No LLM call: ``_fleet_specs([])`` yields the full default fleet (guaranteeing
    the Platform agent among the oversight roles), wired under the CEO with the
    budget split by role.
    """
    mission = Mission(
        company_id=company.id,
        raw_text=settings.galaxia_mission,
        constraints=list(settings.galaxia_constraints),
    )
    db.add(mission)
    await db.flush()
    company.mission_id = mission.id

    await provision_fleet(
        db,
        company=company,
        specs=_fleet_specs([]),
        total_budget_cents=settings.galaxia_monthly_budget_cents,
    )
    # Intentionally left in ``draft``: the founder approves the plan by launching.
    await db.flush()


async def _reconcile_mission(db: AsyncSession, company: Company) -> None:
    """Keep the stored mission in sync with config (config is the source of truth).

    Updates only the mission text and constraints — it does NOT regenerate
    objectives or the fleet (use a reset for that). So editing the mission in
    config takes effect on the next boot even for an already-provisioned Galaxia.
    """
    mission = await db.scalar(select(Mission).where(Mission.company_id == company.id))
    if mission is None:
        return
    desired_constraints = list(settings.galaxia_constraints)
    changed = False
    if mission.raw_text != settings.galaxia_mission:
        mission.raw_text = settings.galaxia_mission
        changed = True
    if (mission.constraints or []) != desired_constraints:
        mission.constraints = desired_constraints
        changed = True
    if changed:
        await db.flush()
        _log.info("Galaxia mission reconciled to config (company=%s)", company.id)


async def _snapshot_api_keys(db: AsyncSession, company_id: uuid.UUID) -> list[dict]:
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


async def _restore_api_keys(
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
