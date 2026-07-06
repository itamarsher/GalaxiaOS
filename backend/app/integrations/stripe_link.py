"""Stripe Link agent wallet — issues Shared Payment Tokens (SPTs).

The wallet owner connects their Link wallet (cards/bank already on file); the
agent obtains a scoped, single-purchase SPT via
``POST /v1/shared_payment/issued_tokens`` (Stripe preview API,
``Stripe-Version: 2026-04-22.preview``). The SPT caps the amount and currency and
is handed to a Stripe-enabled seller to charge — the agent never touches raw card
data.

⚠️  Live Link issuance is US-only preview and, by design, asks the wallet owner
to approve every purchase (Stripe pushes an approval prompt; the ``link-cli``
drives that flow). This adapter performs the server-side issuance call only,
using ``ABOS_STRIPE_SECRET_KEY`` as-is (live moves real money). Off unless
``ABOS_PAYMENT_WALLET=stripe_link``.
"""

from __future__ import annotations

import time

from app.config import settings
from app.integrations._stripe import StripeError, stripe_request
from app.integrations.wallet import IssuedToken, WalletError

_ISSUE_PATH = "/v1/shared_payment/issued_tokens"


class StripeLinkWallet:
    def _require_config(self) -> None:
        missing = []
        if not settings.stripe_secret_key.strip():
            missing.append("ABOS_STRIPE_SECRET_KEY")
        if not settings.stripe_link_network_business_profile.strip():
            missing.append("ABOS_STRIPE_LINK_NETWORK_BUSINESS_PROFILE")
        if not settings.stripe_link_payment_method.strip():
            missing.append("ABOS_STRIPE_LINK_PAYMENT_METHOD")
        if missing:
            raise WalletError(
                f"Stripe Link wallet not configured: {', '.join(missing)} "
                "(see .env.example; provision the PaymentMethod with the link-cli)."
            )

    async def issue_token(
        self,
        *,
        amount_cents: int,
        currency: str = "usd",
        merchant_name: str = "",
        merchant_url: str = "",
        context: str = "",
    ) -> IssuedToken:
        self._require_config()
        if amount_cents <= 0:
            raise WalletError("amount_cents must be positive")

        expires_at = int(time.time()) + settings.stripe_link_token_ttl_seconds
        data = {
            "payment_method": settings.stripe_link_payment_method.strip(),
            "seller_details[network_business_profile]": (
                settings.stripe_link_network_business_profile.strip()
            ),
            "usage_limits[currency]": currency,
            "usage_limits[max_amount]": str(amount_cents),
            "usage_limits[expires_at]": str(expires_at),
            "return_url": (
                settings.stripe_link_return_url.strip()
                or "https://abos.local/agent-checkout/return"
            ),
        }
        # Merchant context rides along so the wallet owner's approval prompt (live
        # mode) shows what the agent is buying and from whom.
        if merchant_name:
            data["metadata[merchant_name]"] = merchant_name
        if merchant_url:
            data["metadata[merchant_url]"] = merchant_url
        if context:
            data["metadata[context]"] = context[:500]

        try:
            body = await stripe_request("POST", _ISSUE_PATH, data=data)
        except StripeError as exc:
            raise WalletError(f"Stripe Link could not issue a token: {exc}") from exc

        token_id = body.get("id")
        if not token_id:
            raise WalletError("Stripe Link returned no SPT id")
        return IssuedToken(
            id=str(token_id),
            kind="shared_payment_token",
            max_amount_cents=amount_cents,
            currency=currency,
            expires_at=expires_at,
        )

    async def revoke(self, token_id: str) -> None:
        if not token_id:
            return
        try:
            await stripe_request("POST", f"{_ISSUE_PATH}/{token_id}/revoke")
        except StripeError as exc:
            raise WalletError(f"Stripe Link could not revoke {token_id}: {exc}") from exc
