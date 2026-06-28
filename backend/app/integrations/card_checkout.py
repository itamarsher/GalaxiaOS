"""Card-checkout registrar — buys a domain with a Stripe Link agent credential.

This is the "buy a domain" test target for *real* agent external spend. Unlike
the Namecheap adapter (whose API draws a pre-funded account balance and cannot
accept a card per call), this registrar is a **Stripe-enabled seller**: it takes
a Shared Payment Token minted by the agent's Stripe Link wallet
(:mod:`app.integrations.stripe_link`) and charges it with a ``PaymentIntent``
(``payment_method_data[shared_payment_granted_token]``) — the exact agentic-commerce
flow Stripe designed for agents paying merchants.

- Availability is real (RDAP, free).
- The charge is a real Stripe ``PaymentIntent`` — with a live key
  (``ABOS_STRIPE_SECRET_KEY``) it moves real money; the budget is reserved first.
- Because no production registrar API accepts a raw card per call, the
  registration *record* is sandboxed (like the ``rdap`` registrar) once payment
  succeeds; wiring a live registrar order API is the one remaining step before
  this buys a production domain.

Off by default (``ABOS_DOMAIN_REGISTRAR=simulated``); select with
``ABOS_DOMAIN_REGISTRAR=card_checkout`` and ``ABOS_PAYMENT_WALLET=stripe_link``.
"""

from __future__ import annotations

import uuid

from app.config import settings
from app.integrations import _pricing
from app.integrations._stripe import StripeError, stripe_request
from app.integrations.availability import rdap_available
from app.integrations.base import DomainQuote, DomainRegistration, RegistrarError
from app.integrations.wallet import get_wallet

# A PaymentIntent in any of these states has authorized the funds we needed.
_PAID_STATES = frozenset({"succeeded", "processing", "requires_capture"})


class CardCheckoutRegistrar:
    async def check(self, domain: str) -> DomainQuote:
        if not _pricing.is_registrable(domain):
            return DomainQuote(domain=domain, available=False, price_cents=0)
        available = await rdap_available(domain, timeout=settings.rdap_timeout_seconds)
        if available is not True:
            return DomainQuote(domain=domain, available=False, price_cents=0)
        return DomainQuote(domain=domain, available=True, price_cents=_pricing.price_cents(domain))

    async def register(self, domain: str) -> DomainRegistration:
        quote = await self.check(domain)
        if not quote.available:
            raise RegistrarError(f"{domain} is not available")

        wallet = get_wallet()
        if wallet is None:
            raise RegistrarError(
                "card_checkout registrar needs a payment wallet "
                "(set ABOS_PAYMENT_WALLET=stripe_link)."
            )

        currency = settings.stripe_currency
        # 1) Agent mints a single-purchase credential capped at the quoted price.
        token = await wallet.issue_token(
            amount_cents=quote.price_cents,
            currency=currency,
            merchant_name=settings.card_checkout_merchant_name,
            merchant_url=settings.card_checkout_merchant_url,
            context=f"Register domain {domain}",
        )

        # 2) Seller charges the credential. Amount must not exceed the SPT cap.
        try:
            intent = await stripe_request(
                "POST",
                "/v1/payment_intents",
                data={
                    "amount": str(quote.price_cents),
                    "currency": currency,
                    "payment_method_data[shared_payment_granted_token]": token.id,
                    "confirm": "true",
                    "description": f"Domain registration: {domain}",
                },
            )
        except StripeError as exc:
            # Free the credential so a failed charge can't be retried against it.
            try:
                await wallet.revoke(token.id)
            except Exception:  # noqa: BLE001 — revoke is best-effort cleanup
                pass
            raise RegistrarError(f"card payment failed for {domain}: {exc}") from exc

        status = intent.get("status")
        if status not in _PAID_STATES:
            raise RegistrarError(f"card payment for {domain} not completed (status: {status})")

        charged = intent.get("amount_received") or intent.get("amount") or quote.price_cents
        ref = intent.get("id") or f"pi_sim:{uuid.uuid4().hex[:12]}"
        return DomainRegistration(domain=domain, price_cents=int(charged), external_ref=str(ref))
