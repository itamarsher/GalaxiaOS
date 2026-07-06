"""Tests for the auto-discovering tool registry."""

from __future__ import annotations

import pytest

from app.runtime.tools import TOOL_SPECS, ToolOutcome, execute_tool


def test_tool_names_are_unique():
    names = [s.name for s in TOOL_SPECS]
    assert len(names) == len(set(names)), "duplicate tool names in registry"


def test_core_tools_present():
    names = {s.name for s in TOOL_SPECS}
    for expected in ("dispatch_task", "report_result", "send_email", "web_search"):
        assert expected in names


def test_every_spec_has_object_schema():
    for s in TOOL_SPECS:
        assert s.input_schema.get("type") == "object"
        assert "properties" in s.input_schema


@pytest.mark.asyncio
async def test_unknown_tool_is_graceful():
    out = await execute_tool(None, None, agent=None, task=None, name="nope", args={})
    assert isinstance(out, ToolOutcome) and "unknown tool" in out.observation
