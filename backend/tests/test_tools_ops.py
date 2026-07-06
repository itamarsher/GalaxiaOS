"""Tests for the OPS tools module — DB-free, no network.

``send_notification`` / ``create_calendar_event`` have no provider behind them and
report the capability is unsupported. ``log_ops_event`` is a genuine internal memory
write and stays (its DB behaviour is covered by the runtime/integration tests).
"""

from __future__ import annotations

import pytest

from app.runtime.tools import TOOL_SPECS
from app.runtime.tools.ops import HANDLERS, SPECS


def test_ops_tools_registered():
    names = {s.name for s in TOOL_SPECS}
    for expected in ("send_notification", "create_calendar_event", "log_ops_event"):
        assert expected in names


def test_every_ops_spec_has_object_schema():
    for s in SPECS:
        assert s.input_schema["type"] == "object"
        assert "properties" in s.input_schema


def test_handlers_match_specs():
    assert set(HANDLERS.keys()) == {s.name for s in SPECS}


def test_handler_keys_are_callable():
    for handler in HANDLERS.values():
        assert callable(handler)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args",
    [
        ("send_notification", {"channel": "slack", "target": "#general", "message": "hi"}),
        ("create_calendar_event", {"title": "Launch review", "when": "tomorrow"}),
    ],
)
async def test_external_handlers_report_unsupported(name, args):
    outcome = await HANDLERS[name](None, None, agent=None, task=None, args=args)
    assert outcome.is_error is True
    assert "not supported" in outcome.observation
    assert "request_capability" in outcome.observation
