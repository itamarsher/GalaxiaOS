"""Invoicing seam — how the finance agent issues customer invoices.

A Protocol describing the shape a real billing provider (Stripe, etc.) would
satisfy. There is deliberately NO simulated invoicer: fabricating an invoice id and
booking it as revenue is exactly the kind of fake outcome that misleads planning.
Until a real adapter is wired, :func:`get_invoicer` returns ``None`` and the
``generate_invoice`` tool reports the capability is unsupported (the agent can
request it). A real adapter can be added later behind :func:`get_invoicer` without
touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Invoice:
    """A generated invoice: a stable id/number plus the amount billed."""

    invoice_id: str
    customer: str
    amount_cents: int
    description: str | None = None


@runtime_checkable
class Invoicer(Protocol):
    def generate(
        self, *, company_id: str, customer: str, amount_cents: int, description: str | None = None
    ) -> Invoice:
        """Produce an invoice via the billing provider."""
        ...


def get_invoicer() -> Invoicer | None:
    """Return the configured invoicer, or ``None`` if none is wired (the default)."""
    return None
