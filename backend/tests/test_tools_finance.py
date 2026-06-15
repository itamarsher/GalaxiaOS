"""Tests for the finance tools module (DB-free)."""

from __future__ import annotations

import pytest

from app.integrations.invoicing import (
    SimulatedInvoicer,
    deterministic_invoice_id,
    get_invoicer,
)
from app.runtime.tools import TOOL_SPECS
from app.runtime.tools.finance import (
    HANDLERS,
    SPECS,
    TRANSACTION_KINDS,
    _dollars,
    format_budget_summary,
    validate_kind,
)

FINANCE_TOOL_NAMES = ("read_financials", "record_transaction", "generate_invoice")


def test_finance_tools_registered():
    names = {s.name for s in TOOL_SPECS}
    for expected in FINANCE_TOOL_NAMES:
        assert expected in names


def test_specs_have_object_schema():
    for spec in SPECS:
        assert spec.input_schema["type"] == "object"


def test_handlers_match_specs():
    assert set(HANDLERS) == {s.name for s in SPECS}


def test_spec_names_are_exactly_assigned():
    assert {s.name for s in SPECS} == set(FINANCE_TOOL_NAMES)


def test_dollars_formats_cents():
    assert _dollars(0) == "$0.00"
    assert _dollars(5) == "$0.05"
    assert _dollars(12345) == "$123.45"
    assert _dollars(100000) == "$1,000.00"


def test_dollars_handles_none():
    assert _dollars(None) == "$0.00"


def test_validate_kind_normalizes():
    assert validate_kind("REVENUE") == "revenue"
    assert validate_kind(" expense ") == "expense"
    for kind in TRANSACTION_KINDS:
        assert validate_kind(kind) == kind


def test_validate_kind_rejects_unknown():
    with pytest.raises(ValueError):
        validate_kind("refund")


def test_format_budget_summary_handles_none():
    assert format_budget_summary(None) == "Monthly budget: not configured."


def test_format_budget_summary_computes_remaining():
    class _B:
        limit_cents = 100000
        spent_cents = 30000
        reserved_cents = 10000

    summary = format_budget_summary(_B())
    assert "limit $1,000.00" in summary
    assert "spent $300.00" in summary
    assert "reserved $100.00" in summary
    assert "remaining $600.00" in summary


def test_deterministic_invoice_id_is_stable():
    a = deterministic_invoice_id("company-1", "Acme", 5000)
    b = deterministic_invoice_id("company-1", "Acme", 5000)
    assert a == b
    assert a.startswith("INV-")


def test_deterministic_invoice_id_varies_with_inputs():
    base = deterministic_invoice_id("company-1", "Acme", 5000)
    assert deterministic_invoice_id("company-2", "Acme", 5000) != base
    assert deterministic_invoice_id("company-1", "Beta", 5000) != base
    assert deterministic_invoice_id("company-1", "Acme", 5001) != base


def test_simulated_invoicer_is_deterministic():
    invoicer = get_invoicer()
    assert isinstance(invoicer, SimulatedInvoicer)
    inv = invoicer.generate(company_id="c1", customer="Acme", amount_cents=2500, description="x")
    assert inv.invoice_id == deterministic_invoice_id("c1", "Acme", 2500)
    assert inv.amount_cents == 2500
    assert inv.customer == "Acme"
