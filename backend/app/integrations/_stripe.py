"""Minimal async Stripe REST client, shared by the Stripe Link wallet and the
Stripe-powered card-checkout registrar.

We talk to Stripe over raw HTTP (httpx) rather than adding the ``stripe`` SDK —
the same dependency-light approach the Namecheap adapter takes. Only the handful
of endpoints the agentic-commerce flow needs are exercised, all form-encoded with
the secret key as HTTP basic-auth username.

Live charges are enabled: whatever ``ABOS_STRIPE_SECRET_KEY`` is set to (test or
live) is used as-is — a live ``sk_live_`` key moves real money. The remaining
spend guards are the budget chokepoint (:class:`~app.runtime.cost_meter.CostMeter`,
which reserves against the company budget before any charge) and the Issuing
card's own ``spending_controls``.
"""

from __future__ import annotations

import httpx

from app.config import settings

_API_BASE = "https://api.stripe.com"


class StripeError(RuntimeError):
    """Raised when a Stripe request fails (bad config, vendor error, network)."""


def _require_secret_key() -> str:
    key = settings.stripe_secret_key.strip()
    if not key:
        raise StripeError("Stripe secret key missing (set ABOS_STRIPE_SECRET_KEY).")
    return key


async def stripe_request(method: str, path: str, *, data: dict | None = None) -> dict:
    """Call the Stripe API and return the parsed JSON body.

    Raises :class:`StripeError` on a missing/refused key, a non-2xx response
    (surfacing Stripe's ``error.message``), or a network/parse failure.
    """
    key = _require_secret_key()
    headers = {"Stripe-Version": settings.stripe_api_version}
    try:
        async with httpx.AsyncClient(timeout=settings.stripe_timeout_seconds) as client:
            resp = await client.request(
                method, f"{_API_BASE}{path}", headers=headers, auth=(key, ""), data=data or {}
            )
    except httpx.HTTPError as exc:
        raise StripeError(f"Stripe request failed: {exc}") from exc

    try:
        body = resp.json()
    except ValueError as exc:
        raise StripeError(f"Stripe returned non-JSON (HTTP {resp.status_code})") from exc
    if resp.status_code >= 400:
        message = body.get("error", {}).get("message") if isinstance(body, dict) else None
        raise StripeError(message or f"Stripe error (HTTP {resp.status_code})")
    return body
