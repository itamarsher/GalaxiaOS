"""A tool call cut off by the output token limit must not be dispatched as-is
(issue #240).

``save_file``/``publish_content`` take large free-text arguments (``content``/
``body``). When the model's response is truncated by ``max_tokens`` mid-JSON,
the provider still returns a ``ToolCall`` — just with a missing or empty
argument — and the old loop dispatched it straight to the handler, which
reported a confusing "content is empty"/"missing argument" error that gave the
agent no way to know its own output had been cut off. The native backend's
step loop now recognizes a truncated stop reason and answers those calls with
an explicit, actionable tool-result error instead of executing them.
"""

from __future__ import annotations

from app.providers.base import LLMResponse, Message, TextBlock, ToolCall, ToolResultBlock
from app.runtime.backends.native import _TRUNCATED_STOP_REASONS, _truncated_tool_result_messages


def _resp(*, stop_reason: str, text: str = "", tool_calls=None) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=tool_calls or [], stop_reason=stop_reason)


def test_anthropic_and_openai_style_truncation_both_recognized():
    # Anthropic reports "max_tokens"; OpenAI-compatible providers (incl. the OSS
    # ones, which subclass OpenAIProvider) report "length".
    assert "max_tokens" in _TRUNCATED_STOP_REASONS
    assert "length" in _TRUNCATED_STOP_REASONS
    # A normal completion must not be treated as truncated.
    assert "end_turn" not in _TRUNCATED_STOP_REASONS
    assert "tool_use" not in _TRUNCATED_STOP_REASONS
    assert "stop" not in _TRUNCATED_STOP_REASONS


def test_truncated_tool_result_messages_echoes_calls_and_errors_each_one():
    calls = [
        ToolCall(id="1", name="save_file", arguments={"name": "spec.md"}),
        ToolCall(id="2", name="publish_content", arguments={"title": "Launch"}),
    ]
    resp = _resp(stop_reason="max_tokens", text="Filing the spec now.", tool_calls=calls)

    assistant_msg, user_msg = _truncated_tool_result_messages(resp)

    assert isinstance(assistant_msg, Message) and assistant_msg.role == "assistant"
    # The model's own text and both tool_use blocks are echoed (ids preserved) so
    # the transcript stays a valid, resumable tool_use/tool_result pairing.
    assert any(isinstance(b, TextBlock) and b.text == "Filing the spec now." for b in assistant_msg.content)
    echoed_ids = {b.id for b in assistant_msg.content if hasattr(b, "id")}
    assert echoed_ids == {"1", "2"}

    assert isinstance(user_msg, Message) and user_msg.role == "user"
    assert len(user_msg.content) == 2
    for block, call in zip(user_msg.content, calls):
        assert isinstance(block, ToolResultBlock)
        assert block.tool_use_id == call.id
        assert block.is_error is True
        # Actionable, not the misleading "content is empty"/"missing argument".
        assert "cut off" in block.content
        assert "retry" in block.content.lower()


def test_truncated_tool_result_messages_handles_no_leading_text():
    calls = [ToolCall(id="1", name="save_file", arguments={})]
    resp = _resp(stop_reason="length", text="", tool_calls=calls)

    assistant_msg, _ = _truncated_tool_result_messages(resp)
    assert all(not isinstance(b, TextBlock) for b in assistant_msg.content)
