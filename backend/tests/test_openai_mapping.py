"""Unit tests for the OpenAI message mapping (no network)."""

from __future__ import annotations

from app.providers.base import Message, TextBlock, ToolResultBlock, ToolUseBlock
from app.providers.openai import _to_oai_messages


def test_plain_string_turns_pass_through_with_system():
    out = _to_oai_messages(
        "you are helpful",
        [Message(role="user", content="hi"), Message(role="assistant", content="hello")],
    )
    assert out == [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_assistant_tool_use_becomes_tool_calls():
    msg = Message(
        role="assistant",
        content=[
            TextBlock(text="calling a tool"),
            ToolUseBlock(id="call_1", name="register_domain", input={"domain": "x.com"}),
        ],
    )
    out = _to_oai_messages("", [msg])
    assert len(out) == 1
    assert out[0]["role"] == "assistant"
    assert out[0]["content"] == "calling a tool"
    (tc,) = out[0]["tool_calls"]
    assert tc["id"] == "call_1"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "register_domain"
    assert tc["function"]["arguments"] == '{"domain": "x.com"}'


def test_tool_results_become_separate_tool_messages():
    msg = Message(
        role="user",
        content=[
            ToolResultBlock(tool_use_id="call_1", content="registered x.com"),
            ToolResultBlock(tool_use_id="call_2", content="blocked", is_error=True),
        ],
    )
    out = _to_oai_messages("", [msg])
    assert out == [
        {"role": "tool", "tool_call_id": "call_1", "content": "registered x.com"},
        {"role": "tool", "tool_call_id": "call_2", "content": "ERROR: blocked"},
    ]


def test_assistant_with_only_tool_use_has_null_content():
    msg = Message(
        role="assistant",
        content=[ToolUseBlock(id="c", name="report_result", input={})],
    )
    out = _to_oai_messages("", [msg])
    assert out[0]["content"] is None
    assert out[0]["tool_calls"][0]["function"]["arguments"] == "{}"


def test_full_round_trip_ordering():
    """Assistant tool_calls must precede their tool result messages."""
    msgs = [
        Message(role="user", content="start"),
        Message(
            role="assistant",
            content=[ToolUseBlock(id="c1", name="dispatch_task", input={"role": "growth"})],
        ),
        Message(role="user", content=[ToolResultBlock(tool_use_id="c1", content="ok")]),
    ]
    out = _to_oai_messages("sys", msgs)
    roles = [m["role"] for m in out]
    assert roles == ["system", "user", "assistant", "tool"]
    assert out[2]["tool_calls"][0]["id"] == "c1"
    assert out[3]["tool_call_id"] == "c1"
