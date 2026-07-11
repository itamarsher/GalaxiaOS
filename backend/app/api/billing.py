"""Managed-mode billing API: a founder's tier/usage + upgrade to paid managed.

Read the platform standing that drives the keyless-launch UX, and start the
Stripe Checkout flow that converts a capped free-tier founder into a paying
managed one. All per-founder (pooled across their companies); scoped through a
company the caller is a member of for a natural place to surface it in the UI.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.deps import CompanyDep, DbDep
from app.integrations._stripe import StripeError
from app.models import User
from app.providers.registry import supported_providers
from app.services import apikeys as apikeys_svc
from app.services import billing, billing_stripe

router = APIRouter(prefix="/companies/{company_id}/managed", tags=["billing"])


@router.get("")
async def managed_status(company: CompanyDep, db: DbDep) -> dict:
    """The owning founder's managed standing + whether this company brought a key."""
    account_status = await billing.status(db, user_id=company.owner_user_id)
    own_keys = await apikeys_svc.list_keys(db, company_id=company.id)
    supported = set(supported_providers())
    byo_llm = [k.provider for k in own_keys if k.provider in supported]
    account_status["has_own_llm_key"] = bool(byo_llm)
    account_status["byo_llm_providers"] = byo_llm
    account_status["upgrade_available"] = billing_stripe.configured()
    return account_status


@router.post("/upgrade")
async def upgrade_to_managed(company: CompanyDep, db: DbDep) -> dict:
    """Begin the Stripe Checkout flow for metered paid-managed usage.

    Returns the Checkout URL to redirect the founder to. The account is promoted
    to ``paid_managed`` only when Stripe confirms via the webhook.
    """
    if not settings.managed_mode_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Managed mode is disabled on this deployment.")
    if not billing_stripe.configured():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Paid managed billing isn't configured (set ABOS_STRIPE_MANAGED_PRICE_ID).",
        )
    owner = await db.get(User, company.owner_user_id)
    base = settings.web_base_url.rstrip("/")
    try:
        url = await billing_stripe.create_checkout_session(
            client_reference_id=str(company.owner_user_id),
            customer_email=owner.email if owner else None,
            success_url=f"{base}/c/{company.id}/settings?managed=upgraded",
            cancel_url=f"{base}/c/{company.id}/settings?managed=cancelled",
        )
    except StripeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return {"url": url}
