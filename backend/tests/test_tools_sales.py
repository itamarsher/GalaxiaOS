"""Tests for the sales tools module (DB-free).

The sales tools have no CRM behind them, so they report the capability is
unsupported instead of fabricating leads/deals/follow-ups.
"""

from __future__ import annotations

import pytest

from app.runtime.tools import TOOL_SPECS
from app.runtime.tools.sales import DEAL_STAGES, HANDLERS, SPECS

SALES_TOOL_NAMES = ("log_lead", "update_deal", "schedule_followup")


def test_sales_tools_registered():
    names = {s.name for s in TOOL_SPECS}
    for expected in SALES_TOOL_NAMES:
        assert expected in names


def test_specs_have_object_schema():
    for spec in SPECS:
        assert spec.input_schema["type"] == "object"
        assert "properties" in spec.input_schema


def test_handlers_match_specs():
    assert set(HANDLERS) == {s.name for s in SPECS}


def test_spec_names_are_exactly_assigned():
    assert {s.name for s in SPECS} == set(SALES_TOOL_NAMES)


def test_update_deal_schema_lists_stages():
    spec = next(s for s in SPECS if s.name == "update_deal")
    assert spec.input_schema["properties"]["stage"]["enum"] == list(DEAL_STAGES)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args",
    [
        ("log_lead", {"name": "Ada"}),
        ("update_deal", {"lead": "Ada", "stage": "won", "amount_cents": 12345}),
        ("schedule_followup", {"lead": "Ada", "when": "next week"}),
    ],
)
async def test_handlers_report_unsupported_and_do_not_fabricate(name, args):
    # No DB / metrics writes happen, so passing ``None`` for db/ctx is safe — the
    # whole point is that nothing is recorded.
    outcome = await HANDLERS[name](None, None, agent=None, task=None, args=args)
    assert outcome.is_error is True
    assert "not supported" in outcome.observation
    assert "request_capability" in outcome.observation
