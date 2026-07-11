"""Stripe Issuing real-time-authorization webhook.

Stripe POSTs ``issuing_authorization.request`` here and waits ~2s for a verdict.
We verify the signature, resolve the owning company from the card metadata, and
approve/decline against that company's budget (see
:mod:`app.services.issuing`). The endpoint is unauthenticated — it is guarded by
the webhook signature, exactly like the public lead-capture sink is guarded by an
unguessable id.
"""

from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, HTTPException, Request, status

from app.config import settings
from app.deps import DbDep
from app.integrations.stripe_issuing import get_issuing_wallet
from app.integrations.wallet import WalletError
from app.services import billing, billing_stripe
from app.services import issuing as issuing_svc

router = APIRouter(prefix="/webhooks/stripe", tags=["stripe"])


@router.post("/issuing")
async def issuing_authorization(request: Request, db: DbDep) -> dict:
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    if not issuing_svc.verify_signature(
        payload, signature, settings.stripe_webhook_secret, now=int(time.time())
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Stripe signature")

    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed payload") from exc

    # Only real-time auth requests need a synchronous verdict; ack everything else.
    if event.get("type") != "issuing_authorization.request":
        return {"received": True}

    auth_obj = event.get("data", {}).get("object", {})
    approved = await issuing_svc.decide_authorization(db, auth_obj)

    wallet = get_issuing_wallet()
    auth_id = auth_obj.get("id")
    if wallet is not None and auth_id:
        try:
            await wallet.authorize(auth_id, approve=approved)
        except WalletError:
            # Stripe falls back to our default (decline) if we can't respond in
            # time; surface nothing card-sensitive to the caller.
            pass
    return {"received": True, "approved": approved}


@router.post("/billing")
async def managed_billing_event(request: Request, db: DbDep) -> dict:
    """Promote a founder to paid managed on a completed Checkout subscription.

    Verifies the Stripe signature (reusing ``ABOS_STRIPE_WEBHOOK_SECRET``), then
    on ``checkout.session.completed`` reads the founder id from
    ``client_reference_id`` and records their subscription item so subsequent
    platform-funded spend is metered to it.
    """
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    if settings.stripe_webhook_secret and not issuing_svc.verify_signature(
        payload, signature, settings.stripe_webhook_secret, now=int(time.time())
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Stripe signature")

    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed payload") from exc

    if event.get("type") != "checkout.session.completed":
        return {"received": True}

    session = event.get("data", {}).get("object", {})
    ref = session.get("client_reference_id")
    if not ref:
        return {"received": True}
    try:
        user_id = uuid.UUID(ref)
    except (ValueError, TypeError):
        return {"received": True}

    item_id = await billing_stripe.resolve_subscription_item_from_session(session)
    await billing.mark_paid_managed(
        db,
        user_id=user_id,
        stripe_customer_id=session.get("customer"),
        stripe_subscription_item_id=item_id,
    )
    await db.commit()
    return {"received": True, "upgraded": True}
