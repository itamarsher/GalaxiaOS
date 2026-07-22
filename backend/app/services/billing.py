"""Managed-mode platform billing: the per-founder free tier → paid managed seam.

This is the accounting the CostMeter alone doesn't provide: the meter tracks a
*company's* spend against the founder's business budget, but says nothing about
*who pays* for it. When a founder brings no key of their own and managed mode is
on, the platform funds their compute — and that platform-funded spend is pooled
per founder ACCOUNT here, capped by a free allowance, and (once they upgrade)
metered into paid usage.

Two dimensions, one chokepoint: the CostMeter still reserves/commits every
billable action against the business budget exactly as before; when the funding
source is the platform, it additionally calls :func:`record_platform_spend`
inside the same commit, so LLM tokens and paid read-only capabilities all funnel
through one ledger.

Eligibility (``platform_available``) is checked at capability-resolution time
(once per task / generation), not per call — coarse but correct: a founder who
crosses the cap mid-task finishes that task, then the next resolution blocks
them until they add a key or upgrade.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Company, PlatformBillingAccount, PlatformCharge
from app.models.enums import ManagedTier


@dataclass(frozen=True)
class Eligibility:
    """Whether platform-funded compute is available to a founder, and why not."""

    allowed: bool
    tier: ManagedTier
    reason: str | None = None


async def get_or_create_account(
    db: AsyncSession, *, user_id: uuid.UUID
) -> PlatformBillingAccount:
    account = await db.scalar(
        select(PlatformBillingAccount).where(PlatformBillingAccount.user_id == user_id)
    )
    if account is None:
        account = PlatformBillingAccount(user_id=user_id, tier=ManagedTier.free)
        db.add(account)
        await db.flush()
    return account


async def _spent_today_cents(db: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Platform-funded spend by this founder since the start of the current UTC day."""
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total = await db.scalar(
        select(func.coalesce(func.sum(PlatformCharge.cents), 0)).where(
            PlatformCharge.user_id == user_id,
            PlatformCharge.created_at >= day_start,
        )
    )
    return int(total or 0)


async def eligibility(db: AsyncSession, *, user_id: uuid.UUID) -> Eligibility:
    """Resolve whether the platform will fund more compute for this founder.

    Order of checks: managed mode + a configured platform key must exist at all;
    then the paid-managed tier is always allowed (they're being billed); then the
    free tier is allowed while under both the lifetime allowance and the daily
    burst cap.
    """
    if not settings.managed_mode_enabled:
        return Eligibility(False, ManagedTier.blocked, "Managed mode is disabled on this deployment.")

    account = await get_or_create_account(db, user_id=user_id)

    if account.tier == ManagedTier.paid_managed:
        # Paid usage is metered and billed; still honour the daily burst guard as
        # an abuse backstop even for paying accounts.
        if settings.platform_daily_cap_cents > 0:
            if await _spent_today_cents(db, user_id=user_id) >= settings.platform_daily_cap_cents:
                return Eligibility(
                    False, account.tier, "Daily platform-usage cap reached; resumes tomorrow."
                )
        return Eligibility(True, account.tier)

    # Free tier: bounded by the lifetime allowance and the daily burst cap.
    if account.platform_spent_cents >= settings.platform_free_tier_cents:
        return Eligibility(
            False,
            ManagedTier.blocked,
            "Free platform allowance used up — add your own model key or upgrade to managed.",
        )
    if settings.platform_daily_cap_cents > 0:
        if await _spent_today_cents(db, user_id=user_id) >= settings.platform_daily_cap_cents:
            return Eligibility(
                False, account.tier, "Daily free-tier cap reached; resumes tomorrow."
            )
    return Eligibility(True, ManagedTier.free)


async def platform_llm_configured() -> bool:
    """True when the deployment can actually supply a managed LLM."""
    return bool(
        settings.managed_mode_enabled
        and settings.platform_llm_provider
        and settings.platform_llm_api_key
    )


async def platform_available(db: AsyncSession, *, company_id: uuid.UUID) -> Eligibility:
    """Eligibility for a company, resolved via its owner (the founder account).

    Every company — including the operator (dogfooding) company — is metered like any
    tenant: the operator company is a normal, normally-funded company, not an
    unlimited house account.
    """
    owner_id = await db.scalar(select(Company.owner_user_id).where(Company.id == company_id))
    if owner_id is None:
        return Eligibility(False, ManagedTier.blocked, "Company has no owner.")
    return await eligibility(db, user_id=owner_id)


async def owner_of(db: AsyncSession, *, company_id: uuid.UUID) -> uuid.UUID | None:
    return await db.scalar(select(Company.owner_user_id).where(Company.id == company_id))


async def platform_capability_funding(
    db: AsyncSession, *, company_id: uuid.UUID
) -> tuple[bool, uuid.UUID | None, str | None]:
    """Decide who funds a paid read-only capability served by the GLOBAL provider.

    Called only on the global-provider fallback path (the company brought no key
    of its own for this capability). Returns ``(allowed, funding_user_id, reason)``:

    - Managed mode OFF (self-host): the operator configured the global provider
      for everyone and eats the cost — allowed, no platform ledger entry.
    - Managed mode ON: the founder's free/paid allowance gates it; when allowed,
      ``funding_user_id`` is the founder so the spend is recorded to their ledger.
    """
    if not settings.managed_mode_enabled:
        return True, None, None
    elig = await platform_available(db, company_id=company_id)
    if not elig.allowed:
        return False, None, elig.reason
    return True, await owner_of(db, company_id=company_id), None


async def record_platform_spend(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID | None,
    cents: int,
    kind: str,
) -> None:
    """Attribute ``cents`` of platform-funded spend to a founder + write the ledger.

    Called inside the CostMeter's own commit transaction (after ``commit_spend``,
    before ``db.commit()``), so business-budget accounting and platform-spend
    accounting land atomically. Best-effort paid-managed usage reporting is
    triggered here too; it must never break the metered action, so it is fired
    lazily and swallowed on error.
    """
    if cents <= 0:
        return
    account = await get_or_create_account(db, user_id=user_id)
    account.platform_spent_cents += cents
    billed = account.tier == ManagedTier.paid_managed
    db.add(
        PlatformCharge(
            user_id=user_id,
            company_id=company_id,
            cents=cents,
            kind=kind,
            billed=billed,
        )
    )
    await db.flush()
    if billed:
        from app.services import billing_stripe

        await billing_stripe.report_usage_safe(account=account, cents=cents)


async def status(db: AsyncSession, *, user_id: uuid.UUID) -> dict:
    """A founder-facing summary of their managed standing (for the UI)."""
    configured = await platform_llm_configured()
    if not settings.managed_mode_enabled:
        return {
            "managed_mode": False,
            "configured": configured,
            "tier": ManagedTier.blocked.value,
            "free_allowance_cents": 0,
            "platform_spent_cents": 0,
            "free_remaining_cents": 0,
            "spent_today_cents": 0,
            "daily_cap_cents": settings.platform_daily_cap_cents,
            "allowed": False,
        }
    account = await get_or_create_account(db, user_id=user_id)
    elig = await eligibility(db, user_id=user_id)
    free_remaining = max(0, settings.platform_free_tier_cents - account.platform_spent_cents)
    return {
        "managed_mode": True,
        "configured": configured,
        "tier": account.tier.value,
        "free_allowance_cents": settings.platform_free_tier_cents,
        "platform_spent_cents": account.platform_spent_cents,
        "free_remaining_cents": free_remaining,
        "spent_today_cents": await _spent_today_cents(db, user_id=user_id),
        "daily_cap_cents": settings.platform_daily_cap_cents,
        "allowed": elig.allowed and configured,
        "reason": elig.reason,
    }


async def mark_paid_managed(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    stripe_customer_id: str | None = None,
    stripe_subscription_item_id: str | None = None,
) -> PlatformBillingAccount:
    """Promote a founder to the paid managed tier (called on successful checkout)."""
    account = await get_or_create_account(db, user_id=user_id)
    account.tier = ManagedTier.paid_managed
    if stripe_customer_id:
        account.stripe_customer_id = stripe_customer_id
    if stripe_subscription_item_id:
        account.stripe_subscription_item_id = stripe_subscription_item_id
    await db.flush()
    return account
