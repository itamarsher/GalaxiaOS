"""Tests for the OPS tools module — DB-free, no network."""

from __future__ import annotations

from app.runtime.tools import TOOL_SPECS
from app.runtime.tools.ops import HANDLERS, SPECS, _deterministic_id


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


def test_deterministic_id_is_stable():
    a = _deterministic_id("notif", "co1", "slack", "#general", "hello")
    b = _deterministic_id("notif", "co1", "slack", "#general", "hello")
    assert a == b
    assert a.startswith("notif_")


def test_deterministic_id_varies_with_inputs():
    a = _deterministic_id("evt", "co1", "Launch review", "tomorrow")
    b = _deterministic_id("evt", "co1", "Launch review", "next week")
    assert a != b
    # Prefix is honored and the id is compact.
    assert a.startswith("evt_")
    assert len(a) == len("evt_") + 16
