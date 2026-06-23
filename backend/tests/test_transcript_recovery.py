"""Tool-call recovery hardening: a resumed transcript is always valid.

Pure, DB-free — exercises ``sanitize_messages`` against the dangling-tool_use
shapes an interrupted step can leave behind.
"""

from __future__ import annotations

from app.providers.base import Message, TextBlock, ToolResultBlock, ToolUseBlock
from app.runtime.transcript import sanitize_messages


def _use(id_: str) -> Message:
    return Message(role="assistant", content=[ToolUseBlock(id=id_, name="web_search", input={})])


def _result_ids(msg: Message) -> set[str]:
    return {b.tool_use_id for b in msg.content if isinstance(b, ToolResultBlock)}


def test_dangling_tool_use_at_end_gets_synthetic_result() -> None:
    messages = [Message(role="user", content="Begin"), _use("call_1")]
    repaired = sanitize_messages(messages)
    # A user result turn is appended so the tool_use is answered.
    assert repaired[-1].role == "user"
    assert "call_1" in _result_ids(repaired[-1])
    assert repaired[-1].content[0].is_error is True


def test_partial_results_are_completed() -> None:
    messages = [
        Message(role="user", content="Begin"),
        Message(
            role="assistant",
            content=[ToolUseBlock(id="a", name="x", input={}), ToolUseBlock(id="b", name="y", input={})],
        ),
        Message(role="user", content=[ToolResultBlock(tool_use_id="a", content="ok")]),
    ]
    repaired = sanitize_messages(messages)
    # The missing result for "b" is injected into the existing result turn.
    assert _result_ids(repaired[2]) == {"a", "b"}


def test_complete_transcript_is_unchanged_shape() -> None:
    messages = [
        Message(role="user", content="Begin"),
        Message(role="assistant", content=[ToolUseBlock(id="a", name="x", input={})]),
        Message(role="user", content=[ToolResultBlock(tool_use_id="a", content="ok")]),
        Message(role="assistant", content=[TextBlock(text="done")]),
    ]
    repaired = sanitize_messages(messages)
    assert len(repaired) == len(messages)
    assert _result_ids(repaired[2]) == {"a"}
