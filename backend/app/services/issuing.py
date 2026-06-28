"""Budget gate for Stripe Issuing real-time authorizations.

When the fleet's virtual card is charged (e.g. topping up the registrar balance),
Stripe sends an ``issuing_authorization.request`` webhook and waits ~2s for an
approve/decline. :func:`decide_authorization` answers it against the owning
company's budget: approve only when the requested amount fits the remaining
headroom (``limit − spent − reserved``). The owning company comes from the card's
``metadata.company_id`` (stamped at provision time).

This is a *ceiling* check, not a reservation: the real spend is committed through
:class:`~app.runtime.cost_meter.CostMeter` when funds are consumed (the domain is
registered), so funding and purchase are not double-counted. The gate's job is to
guarantee the card can never be charged beyond the company's hard budget.

Signature verification (:func:`verify_signature`) follows Stripe's scheme:
``HMAC-SHA256(secret, "{timestamp}.{payload}")`` compared to the ``v1`` value in
the ``Stripe-Signature`` header, within a timestamp tolerance.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import set_tenant
from app.services import budget as budget_svc


def _parse_signature_header(header: str) -> tuple[int | None, list[str]]:
    timestamp: int | None = None
    signatures: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                timestamp = None
        elif key == "v1":
            signatures.append(value)
    return timestamp, signatures


def verify_signature(
    payload: bytes, header: str, secret: str, *, now: int, tolerance: int = 300
) -> bool:
    """Return True iff ``header`` is a valid Stripe signature for ``payload``.

    ``now`` is passed in (not read from the clock) so the check is deterministic
    and unit-testable. A blank secret or header fails closed.
    """
    if not secret or not header:
        return False
    timestamp, signatures = _parse_signature_header(header)
    if timestamp is None or not signatures:
        return False
    if abs(now - timestamp) > tolerance:
        return False
    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, sig) for sig in signatures)


def authorization_amount(auth_obj: dict) -> int:
    """The cents Stripe is asking us to authorize (pending request, then amount)."""
    pending = auth_obj.get("pending_request") or {}
    return int(pending.get("amount") or auth_obj.get("amount") or 0)


def authorization_company_id(auth_obj: dict) -> str | None:
    """The owning company id stamped on the card's metadata, if present."""
    metadata = (auth_obj.get("card") or {}).get("metadata") or {}
    return metadata.get("company_id") or None


async def decide_authorization(db: AsyncSession, auth_obj: dict) -> bool:
    """Approve the authorization iff it fits the owning company's budget headroom.

    Fails closed: unknown company, no active budget, or a non-positive amount all
    decline.
    """
    raw_company = authorization_company_id(auth_obj)
    amount = authorization_amount(auth_obj)
    if not raw_company or amount <= 0:
        return False
    try:
        company_id = uuid.UUID(raw_company)
    except ValueError:
        return False

    await set_tenant(db, company_id)
    budget = await budget_svc.get_active_budget(db, company_id)
    if budget is None:
        return False
    headroom = budget.limit_cents - budget.spent_cents - budget.reserved_cents
    return amount <= headroom
