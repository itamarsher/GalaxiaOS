"""Stripe Issuing — a real, budget-controlled virtual card for agent spend.

Issuing mints a genuine virtual card (a real PAN on card rails) the fleet uses to
fund external accounts — e.g. topping up the registrar balance the ``namecheap``
adapter draws down. Unlike the Link wallet, Issuing authorizes purchases
*programmatically*: Stripe calls a real-time-authorization webhook
(:mod:`app.api.stripe_webhooks`) that decides approve/decline against the company
budget, so no human signs off each charge.

Card creation goes through ``POST /v1/issuing/cards`` with hard
``spending_controls`` (a monthly cap, optional allowed merchant categories), and
the owning company is stamped into the card's metadata so the webhook can find
the budget to gate against. Test-mode first (``ABOS_STRIPE_TEST_MODE=true``); the
live-key guard in :mod:`app.integrations._stripe` blocks ``sk_live_`` keys until
you opt in. It has not been exercised against the live API in this repo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.config import settings
from app.integrations._stripe import StripeError, stripe_request
from app.integrations.wallet import WalletError


@dataclass(frozen=True)
class IssuedCard:
    """A provisioned virtual card (no PAN — fetch card details separately)."""

    id: str  # ic_…
    last4: str
    brand: str
    exp_month: int
    exp_year: int
    status: str
    company_id: str


def _to_card(body: dict) -> IssuedCard:
    return IssuedCard(
        id=str(body.get("id", "")),
        last4=str(body.get("last4", "")),
        brand=str(body.get("brand", "")),
        exp_month=int(body.get("exp_month") or 0),
        exp_year=int(body.get("exp_year") or 0),
        status=str(body.get("status", "")),
        company_id=str((body.get("metadata") or {}).get("company_id", "")),
    )


class StripeIssuingWallet:
    def _require_config(self) -> None:
        if not settings.stripe_secret_key.strip():
            raise WalletError("Stripe Issuing not configured: set ABOS_STRIPE_SECRET_KEY.")
        if not settings.stripe_issuing_cardholder.strip():
            raise WalletError(
                "Stripe Issuing needs a cardholder: set ABOS_STRIPE_ISSUING_CARDHOLDER "
                "(create one in Stripe — ich_…)."
            )

    async def provision_card(
        self,
        *,
        company_id: uuid.UUID,
        monthly_limit_cents: int | None = None,
        allowed_categories: list[str] | None = None,
        label: str = "",
    ) -> IssuedCard:
        """Create a virtual card for ``company_id`` with a hard monthly cap.

        The cap defaults to ``settings.stripe_issuing_monthly_limit_cents`` and is
        a backstop independent of the per-authorization budget gate. The owning
        company is stored in metadata so the webhook can resolve its budget.
        """
        self._require_config()
        limit = monthly_limit_cents or settings.stripe_issuing_monthly_limit_cents
        if limit <= 0:
            raise WalletError("monthly_limit_cents must be positive")

        data = {
            "cardholder": settings.stripe_issuing_cardholder.strip(),
            "currency": settings.stripe_currency,
            "type": "virtual",
            "spending_controls[spending_limits][0][amount]": str(limit),
            "spending_controls[spending_limits][0][interval]": "monthly",
            "metadata[company_id]": str(company_id),
        }
        if label:
            data["metadata[label]"] = label
        for i, category in enumerate(allowed_categories or []):
            data[f"spending_controls[allowed_categories][{i}]"] = category

        try:
            body = await stripe_request("POST", "/v1/issuing/cards", data=data)
        except StripeError as exc:
            raise WalletError(f"Stripe Issuing could not create a card: {exc}") from exc
        return _to_card(body)

    async def authorize(self, authorization_id: str, *, approve: bool) -> None:
        """Approve or decline a pending Issuing authorization."""
        if not authorization_id:
            raise WalletError("authorization_id is required")
        action = "approve" if approve else "decline"
        try:
            await stripe_request("POST", f"/v1/issuing/authorizations/{authorization_id}/{action}")
        except StripeError as exc:
            raise WalletError(f"Stripe Issuing {action} failed: {exc}") from exc


def get_issuing_wallet() -> StripeIssuingWallet | None:
    """Return the Issuing wallet if a Stripe secret key is configured, else None."""
    if not settings.stripe_secret_key.strip():
        return None
    return StripeIssuingWallet()
