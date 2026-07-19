"""Tests for the finance tools module (DB-free).

``read_financials`` / ``record_transaction`` operate on the company's own data and
stay. ``generate_invoice`` has no billing provider behind it, so it reports the
capability is unsupported instead of fabricating an invoice.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.integrations.invoicing import get_invoicer
from app.models.enums import AgentRole
from app.runtime.tools import TOOL_SPECS
from app.runtime.tools.finance import (
    HANDLERS,
    SPECS,
    TRANSACTION_KINDS,
    _dollars,
    _read_financials,
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


async def test_read_financials_gated_on_financial_label():
    """An agent without the ``financial`` label is denied before any DB read; the
    denial short-circuits, so no session is touched (db=None here proves it)."""
    task = SimpleNamespace(company_id=uuid.uuid4())
    uncleared = SimpleNamespace(id=uuid.uuid4(), role=AgentRole.growth, access_labels=["customers"])
    out = await _read_financials(None, None, agent=uncleared, task=task, args={})
    assert out.is_error and "financials" in out.observation


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


def test_no_invoicer_is_wired_by_default():
    # No real billing provider -> None, so generate_invoice reports unsupported.
    assert get_invoicer() is None


@pytest.mark.asyncio
async def test_generate_invoice_reports_unsupported():
    outcome = await HANDLERS["generate_invoice"](
        None, None, agent=None, task=None,
        args={"customer": "Acme", "amount_cents": 2500, "description": "x"},
    )
    assert outcome.is_error is True
    assert "not supported" in outcome.observation
    assert "request_capability" in outcome.observation
