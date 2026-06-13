"""Unit tests for Message -> Anthropic content-block serialization.

No DB or network: exercises the pure rendering/estimation helpers in
``app.providers.anthropic`` and the content-block model in ``app.providers.base``.
"""

from __future__ import annotations

from app.providers.anthropic import _message_text, _render_content
from app.providers.base import (
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def test_plain_string_content_passes_through():
    # Back-compat: a plain-string turn serializes to the same string.
    assert _render_content("hello world") == "hello world"


def test_tool_use_block_renders_to_anthropic_shape():
    blocks = [
        TextBlock(text="let me check"),
        ToolUseBlock(id="tu_1", name="register_domain", input={"domain": "x.com"}),
    ]
    rendered = _render_content(blocks)
    assert rendered == [
        {"type": "text", "text": "let me check"},
        {
            "type": "tool_use",
            "id": "tu_1",
            "name": "register_domain",
            "input": {"domain": "x.com"},
        },
    ]


def test_tool_result_block_renders_with_matching_id_and_error_flag():
    blocks = [
        ToolResultBlock(tool_use_id="tu_1", content="registered ok"),
        ToolResultBlock(tool_use_id="tu_2", content="DENIED by policy", is_error=True),
    ]
    rendered = _render_content(blocks)
    assert rendered == [
        {
            "type": "tool_result",
            "tool_use_id": "tu_1",
            "content": "registered ok",
            "is_error": False,
        },
        {
            "type": "tool_result",
            "tool_use_id": "tu_2",
            "content": "DENIED by policy",
            "is_error": True,
        },
    ]


def test_tool_use_block_defaults_empty_input_to_dict():
    rendered = _render_content([ToolUseBlock(id="t", name="noop", input={})])
    assert rendered[0]["input"] == {}


def test_message_text_flattens_string_and_structured_content():
    assert _message_text(Message(role="user", content="abc")) == "abc"
    structured = Message(
        role="assistant",
        content=[
            TextBlock(text="hi"),
            ToolUseBlock(id="t", name="tool", input={"k": "v"}),
            ToolResultBlock(tool_use_id="t", content="done"),
        ],
    )
    text = _message_text(structured)
    # Estimation only needs an approximate char length; assert it captures parts.
    assert "hi" in text and "tool" in text and "done" in text
