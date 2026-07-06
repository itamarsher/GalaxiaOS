"""Tool-call recovery hardening: a resumed transcript is always valid.

Pure, DB-free — exercises ``sanitize_messages`` against the dangling-tool_use
shapes an interrupted step can leave behind.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.providers.base import Message, TextBlock, ToolResultBlock, ToolUseBlock
from app.runtime.backends.native import NativeBackend
from app.runtime.transcript import dump_messages, sanitize_messages


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


# ── The system prompt never lives in the replayed message history ─────────────
def test_resume_strips_any_system_role_turn() -> None:
    """A resumed transcript carries only user/assistant turns — never the system prompt.

    The system prompt is passed out-of-band on every call and rebuilt each run, so a
    stray ``system`` turn in the persisted history would duplicate it into the
    context window. ``_resume_or_seed`` drops any such turn defensively.
    """
    transcript = dump_messages(
        [
            Message(role="system", content="You are the Growth agent. <huge system prompt>"),
            Message(role="user", content="Begin: do the thing"),
            Message(role="assistant", content=[TextBlock(text="on it")]),
        ]
    )
    task = SimpleNamespace(transcript=transcript, goal="do the thing")
    resumed = NativeBackend._resume_or_seed(NativeBackend(), task)
    assert [m.role for m in resumed] == ["user", "assistant"]
    assert all(m.role in ("user", "assistant") for m in resumed)


def test_seed_when_no_transcript() -> None:
    task = SimpleNamespace(transcript=None, goal="ship it")
    seeded = NativeBackend._resume_or_seed(NativeBackend(), task)
    assert len(seeded) == 1
    assert seeded[0].role == "user" and "ship it" in seeded[0].content


# ── The chat-catch-up nudge attaches cleanly to the trailing user turn ────────
def test_append_user_note_extends_string_turn() -> None:
    messages = [Message(role="user", content="Begin: x")]
    NativeBackend._append_user_note(messages, "📨 new chat")
    assert messages[-1].role == "user"
    assert "Begin: x" in messages[-1].content and "📨 new chat" in messages[-1].content


def test_append_user_note_appends_after_tool_results() -> None:
    # A trailing tool_result turn keeps role alternation; the note goes after the
    # results (a valid Anthropic ordering), not as a new consecutive user turn.
    messages = [
        Message(role="assistant", content=[ToolUseBlock(id="a", name="x", input={})]),
        Message(role="user", content=[ToolResultBlock(tool_use_id="a", content="ok")]),
    ]
    NativeBackend._append_user_note(messages, "catch up on chat")
    assert len(messages) == 2  # no new turn added
    blocks = messages[-1].content
    assert isinstance(blocks[0], ToolResultBlock)
    assert isinstance(blocks[-1], TextBlock) and "catch up on chat" in blocks[-1].text
