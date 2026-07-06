"""On-demand tool discovery + hot-loading.

Covers the registry split (core vs discoverable), the discover_tools / use_tool
handlers, and the native backend's per-task active-tool tracking (including resume
replay) — the mechanism that lets agents load tools on demand instead of receiving
every tool up front, without breaking request_capability.
"""

from __future__ import annotations

import pytest

from app.providers.base import Message, ToolCall, ToolUseBlock
from app.runtime.backends.native import (
    _absorb_use_tool,
    _active_tools_from_messages,
    _names_from_use_tool_call,
)
from app.runtime.tools import (
    CORE_TOOL_NAMES,
    all_categories,
    core_specs,
    discoverable_catalog,
    execute_tool,
    is_known_tool,
    resolve_tool_names,
    specs_for,
)


# ── Registry ──────────────────────────────────────────────────────────────────
def test_core_tools_are_a_small_subset_and_include_essentials():
    core = CORE_TOOL_NAMES
    # The loop's control surface + escalation + discovery must always be present.
    for must in (
        "report_result",
        "dispatch_task",
        "request_capability",
        "report_bug",
        "discover_tools",
        "use_tool",
        "write_memory",
    ):
        assert must in core
    # Discoverable tools must NOT be core (that's the whole point).
    for not_core in ("send_email", "generate_image", "publish_content", "crm_save_contact"):
        assert not_core not in core
    # core_specs reflects exactly the core names.
    assert {s.name for s in core_specs()} == set(core)


def test_specs_for_unions_core_with_active_and_dedups():
    specs = specs_for(["send_email", "send_email", "generate_video"])
    names = [s.name for s in specs]
    # Core always present.
    assert "report_result" in names and "discover_tools" in names
    # Requested tools present, exactly once each.
    assert names.count("send_email") == 1
    assert "generate_video" in names
    # Unknown names are silently skipped (use_tool validates upstream).
    assert "totally_made_up" not in [s.name for s in specs_for(["totally_made_up"])]


def test_resolve_tool_names_splits_known_unknown_and_drops_core():
    loadable, unknown = resolve_tool_names(
        ["send_email", "generate_image", "write_memory", "", "send_email", "nope"]
    )
    assert loadable == ["send_email", "generate_image"]  # order-preserving, deduped
    assert "write_memory" not in loadable  # core => already on, dropped
    assert unknown == ["nope"]


def test_discoverable_catalog_excludes_core_and_filters():
    # A query matches names/summaries/categories; core tools never appear.
    email_rows = discoverable_catalog(query="email")
    assert any(r["name"] == "send_email" for r in email_rows)
    assert all(r["name"] not in CORE_TOOL_NAMES for r in email_rows)
    # Category browse returns only that category.
    fin = discoverable_catalog(category="finance")
    assert fin and all(r["category"] == "finance" for r in fin)
    # exclude drops already-active tools.
    excluded = discoverable_catalog(query="email", exclude={"send_email"})
    assert all(r["name"] != "send_email" for r in excluded)


def test_all_categories_are_nonempty_and_known():
    cats = all_categories()
    assert "finance" in cats and "design" in cats and "crm" in cats
    for c in cats:
        assert discoverable_catalog(category=c)  # each category has ≥1 tool


def test_is_known_tool():
    assert is_known_tool("generate_image")
    assert is_known_tool("report_result")
    assert not is_known_tool("imaginary_tool")


# ── Backend active-tool tracking ─────────────────────────────────────────────
def test_names_from_use_tool_call_filters_to_loadable():
    # Core/unknown names are dropped; only real discoverable tools remain.
    assert _names_from_use_tool_call({"names": ["send_email", "report_result", "bogus"]}) == [
        "send_email"
    ]
    assert _names_from_use_tool_call({"names": "generate_image"}) == ["generate_image"]
    assert _names_from_use_tool_call({}) == []
    assert _names_from_use_tool_call(None) == []


def test_active_tools_seed_is_core_for_fresh_task():
    msgs = [Message(role="user", content="Begin: do the thing")]
    assert _active_tools_from_messages(msgs) == set(CORE_TOOL_NAMES)


def test_active_tools_replayed_from_transcript():
    # A resumed task rebuilds its loaded set from prior use_tool calls in the history.
    msgs = [
        Message(role="user", content="Begin"),
        Message(
            role="assistant",
            content=[ToolUseBlock(id="1", name="use_tool", input={"names": ["send_email"]})],
        ),
        Message(role="user", content="loaded"),
        Message(
            role="assistant",
            content=[
                ToolUseBlock(id="2", name="use_tool", input={"names": ["generate_image", "x"]}),
                ToolUseBlock(id="3", name="discover_tools", input={"query": "crm"}),
            ],
        ),
    ]
    active = _active_tools_from_messages(msgs)
    assert "send_email" in active and "generate_image" in active
    assert active >= set(CORE_TOOL_NAMES)
    assert "x" not in active  # unknown name not loaded


def test_absorb_use_tool_grows_active_set():
    active = set(CORE_TOOL_NAMES)
    calls = [
        ToolCall(id="1", name="use_tool", arguments={"names": ["publish_content"]}),
        ToolCall(id="2", name="record_metric", arguments={"name": "x", "value": 1}),
    ]
    _absorb_use_tool(active, calls)
    assert "publish_content" in active
    # Non-use_tool calls don't add anything.
    assert "record_metric" in CORE_TOOL_NAMES  # already core, unaffected


# ── Discovery tool handlers ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_discover_tools_handler_lists_matches():
    out = await execute_tool(
        None, None, agent=None, task=None, name="discover_tools", args={"query": "invoice"}
    )
    assert not out.is_error
    assert "generate_invoice" in out.observation
    assert "use_tool" in out.observation  # nudges the next step


@pytest.mark.asyncio
async def test_discover_tools_handler_empty_points_to_request_capability():
    out = await execute_tool(
        None,
        None,
        agent=None,
        task=None,
        name="discover_tools",
        args={"query": "zzz_no_such_capability"},
    )
    assert "request_capability" in out.observation
    assert "categories" in out.observation.lower()


@pytest.mark.asyncio
async def test_use_tool_handler_confirms_and_flags_unknown():
    out = await execute_tool(
        None,
        None,
        agent=None,
        task=None,
        name="use_tool",
        args={"names": ["send_email", "made_up_tool"]},
    )
    assert "send_email" in out.observation
    assert "made_up_tool" in out.observation
    assert "request_capability" in out.observation  # unknown => point at the build path


@pytest.mark.asyncio
async def test_use_tool_handler_all_unknown_is_error():
    out = await execute_tool(
        None, None, agent=None, task=None, name="use_tool", args={"names": ["nope1", "nope2"]}
    )
    assert out.is_error
    assert "request_capability" in out.observation


@pytest.mark.asyncio
async def test_use_tool_handler_requires_names():
    out = await execute_tool(None, None, agent=None, task=None, name="use_tool", args={})
    assert out.is_error
