"""Stripe adapter for the paid managed tier (usage-based billing of platform spend).

Distinct from the agent-facing Stripe seams (Issuing / Link, which give an agent
real money to spend on the company's behalf): this bills the *founder* for the
platform-funded compute they consume once they cross the free tier. It reuses the
shared ``ABOS_STRIPE_SECRET_KEY`` and the minimal HTTP client, and is entirely
feature-flagged: with no ``ABOS_STRIPE_MANAGED_PRICE_ID`` the upgrade flow reports
it's not configured and usage reporting no-ops — exactly the "seam reports
unsupported when unconfigured" pattern the rest of the codebase uses.

Flow: founder clicks Upgrade → :func:`create_checkout_session` returns a Stripe
Checkout URL for a metered subscription → on ``checkout.session.completed`` the
account is promoted to ``paid_managed`` and its subscription item recorded →
thereafter every platform-funded charge calls :func:`report_usage_safe`, which
pushes a usage record (cents × markup) onto that item.
"""

from __future__ import annotations

from app.config import settings
from app.integrations._stripe import StripeError, stripe_request
from app.models import PlatformBillingAccount


def configured() -> bool:
    """True when paid managed billing can actually run (key + metered price set)."""
    return bool(settings.stripe_secret_key.strip() and settings.stripe_managed_price_id.strip())


async def create_checkout_session(
    *,
    client_reference_id: str,
    customer_email: str | None,
    success_url: str,
    cancel_url: str,
) -> str:
    """Create a metered subscription Checkout Session; return its URL.

    ``client_reference_id`` is the founder's user id, echoed back on the
    ``checkout.session.completed`` webhook so we can promote the right account.
    """
    if not configured():
        raise StripeError(
            "Paid managed billing is not configured (set ABOS_STRIPE_MANAGED_PRICE_ID)."
        )
    data = {
        "mode": "subscription",
        "line_items[0][price]": settings.stripe_managed_price_id.strip(),
        "client_reference_id": client_reference_id,
        "success_url": success_url,
        "cancel_url": cancel_url,
    }
    if customer_email:
        data["customer_email"] = customer_email
    body = await stripe_request("POST", "/v1/checkout/sessions", data=data)
    url = body.get("url")
    if not url:
        raise StripeError("Stripe did not return a Checkout URL.")
    return url


async def _subscription_item_id(subscription_id: str) -> str | None:
    """The first (metered) subscription item on a subscription, or ``None``."""
    try:
        body = await stripe_request("GET", f"/v1/subscriptions/{subscription_id}")
    except StripeError:
        return None
    items = (body.get("items") or {}).get("data") or []
    return items[0].get("id") if items else None


async def resolve_subscription_item_from_session(session: dict) -> str | None:
    """Given a completed Checkout Session object, find its subscription item id."""
    subscription_id = session.get("subscription")
    if not subscription_id:
        return None
    return await _subscription_item_id(subscription_id)


async def report_usage_safe(*, account: PlatformBillingAccount, cents: int) -> None:
    """Best-effort: push a metered usage record for ``cents`` (× markup). Never raises.

    No-ops silently when billing isn't configured or the account has no
    subscription item yet — usage reporting must never break the metered action
    that triggered it.
    """
    if cents <= 0 or not configured() or not account.stripe_subscription_item_id:
        return
    quantity = max(1, round(cents * settings.managed_billing_markup))
    try:
        await stripe_request(
            "POST",
            f"/v1/subscription_items/{account.stripe_subscription_item_id}/usage_records",
            data={"quantity": str(quantity), "action": "increment"},
        )
    except StripeError:
        # Swallowed by design; the platform_charges ledger remains the source of
        # truth and a reconciliation pass can replay unbilled rows later.
        return
