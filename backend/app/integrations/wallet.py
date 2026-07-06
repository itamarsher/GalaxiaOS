"""Payment-wallet seam: an agent's scoped access to *real* external spend.

A :class:`PaymentWallet` issues a single-purchase payment credential — a Stripe
Link Shared Payment Token (SPT) — scoped to one merchant and a hard maximum
amount. A Stripe-enabled seller then charges that credential; the wallet itself
never moves money and never touches the budget.

As with the registrar seam, money is metered at the runtime chokepoint: the
``register_domain`` tool wraps the seller's charge in
:meth:`~app.runtime.cost_meter.CostMeter.metered_external`, so the budget is
reserved *before* the irreversible charge. The wallet just mints the credential.

Selection is driven by ``settings.payment_wallet`` (env ``ABOS_PAYMENT_WALLET``):

- ``none`` (default) — no wallet wired; :func:`get_wallet` returns ``None`` and
  any capability needing real external spend reports it is unsupported rather
  than fabricating a charge.
- ``stripe_link`` — the real Stripe Link agent wallet (credential-gated,
  test-mode first). See :mod:`app.integrations.stripe_link`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.config import settings


@dataclass(frozen=True)
class IssuedToken:
    """A scoped, single-purchase credential the seller can charge once."""

    id: str  # opaque vendor token id (e.g. an SPT ``spt_…``)
    kind: str  # "shared_payment_token"
    max_amount_cents: int  # the credential will not authorize more than this
    currency: str
    expires_at: int  # unix timestamp after which the credential is unusable


class WalletError(RuntimeError):
    """Raised when a wallet can't mint/revoke a credential (no creds, vendor error)."""


@runtime_checkable
class PaymentWallet(Protocol):
    async def issue_token(
        self,
        *,
        amount_cents: int,
        currency: str,
        merchant_name: str,
        merchant_url: str,
        context: str,
    ) -> IssuedToken:
        """Mint a credential capped at ``amount_cents`` for one purchase.

        ``merchant_*`` and ``context`` describe the purchase to the wallet owner
        (live Link issuance asks them to approve each spend). Raises
        :class:`WalletError` on misconfiguration or vendor failure. Must NOT touch
        the budget — the caller meters the charge.
        """
        ...

    async def revoke(self, token_id: str) -> None:
        """Best-effort revoke an issued credential so it can't be reused."""
        ...


def get_wallet(name: str | None = None) -> PaymentWallet | None:
    """Return the configured payment wallet, or ``None`` if none is wired.

    ``name`` overrides ``settings.payment_wallet`` when given. The default
    (``none``) returns ``None`` so capabilities report "unsupported" instead of
    fabricating a credential. Unknown names raise ``ValueError`` so a
    misconfiguration fails loudly rather than silently mis-routing real spend.
    """
    key = (name or settings.payment_wallet).strip().lower()

    if key == "none":
        return None
    if key == "stripe_link":
        from app.integrations.stripe_link import StripeLinkWallet

        return StripeLinkWallet()
    raise ValueError(f"unknown payment wallet: {key!r}")
