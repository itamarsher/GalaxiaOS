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

from fastapi import APIRouter, HTTPException, Request, status

from app.config import settings
from app.deps import DbDep
from app.integrations.stripe_issuing import get_issuing_wallet
from app.integrations.wallet import WalletError
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
