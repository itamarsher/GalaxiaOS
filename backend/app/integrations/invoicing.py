"""Invoicing seam — how the finance agent issues customer invoices.

Mirrors the other integration seams (``email``, ``websearch``): a Protocol plus
a deterministic, network-free ``simulated`` default so the agent loop and tests
never call a real billing provider. Issuing an invoice is *not* a real-money
charge — it bills a customer rather than spending the company's budget — so it
deliberately does not route through ``ctx.cost_meter``.

There is no config setting for this seam; it is simulated-only today, and a real
adapter (Stripe, etc.) can be added later behind ``get_invoicer`` without
touching callers.
"""

from __future__ import annotations

import hashlib
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
        """Produce an invoice. Deterministic for a given set of inputs."""
        ...


def deterministic_invoice_id(company_id: str, customer: str, amount_cents: int) -> str:
    """Stable, network-free invoice number — same inputs always yield the same id."""
    digest = hashlib.sha256(f"{company_id}|{customer}|{amount_cents}".encode()).hexdigest()[:10]
    return f"INV-{digest.upper()}"


class SimulatedInvoicer:
    """Deterministic, offline invoicer. Same inputs -> same invoice id; no network."""

    def generate(
        self, *, company_id: str, customer: str, amount_cents: int, description: str | None = None
    ) -> Invoice:
        return Invoice(
            invoice_id=deterministic_invoice_id(company_id, customer, amount_cents),
            customer=customer,
            amount_cents=amount_cents,
            description=description,
        )


def get_invoicer() -> Invoicer:
    """Return the configured invoicer (simulated-only today)."""
    return SimulatedInvoicer()
