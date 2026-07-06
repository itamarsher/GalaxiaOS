"""Working-memory persistence: serialize/restore an in-flight task transcript.

Pure and DB-free — these exercise the JSONB wire shape and the loop's
resume-or-seed decision without standing up Postgres.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.config import settings
from app.providers.base import Message, TextBlock, ToolResultBlock, ToolUseBlock
from app.runtime.backends.native import NativeBackend
from app.runtime.transcript import dump_messages, load_messages, transcript_lines


def _sample_messages() -> list[Message]:
    return [
        Message(role="user", content="Begin: launch the company"),
        Message(
            role="assistant",
            content=[
                TextBlock(text="Planning the launch."),
                ToolUseBlock(
                    id="tu_1", name="record_metric", input={"name": "signups", "value": 3}
                ),
            ],
        ),
        Message(
            role="user",
            content=[ToolResultBlock(tool_use_id="tu_1", content="ok", is_error=False)],
        ),
    ]


def test_transcript_roundtrip_preserves_structure() -> None:
    restored = load_messages(dump_messages(_sample_messages()))

    assert len(restored) == 3
    assert restored[0].role == "user"
    assert restored[0].content == "Begin: launch the company"

    blocks = restored[1].content
    assert isinstance(blocks[0], TextBlock) and blocks[0].text == "Planning the launch."
    assert isinstance(blocks[1], ToolUseBlock)
    assert blocks[1].id == "tu_1"
    assert blocks[1].name == "record_metric"
    assert blocks[1].input == {"name": "signups", "value": 3}

    result = restored[2].content[0]
    assert isinstance(result, ToolResultBlock)
    assert result.tool_use_id == "tu_1"
    assert result.content == "ok"
    assert result.is_error is False


def test_dump_is_json_serializable() -> None:
    # Must survive a JSONB round-trip (json dumps/loads) unchanged.
    dumped = dump_messages(_sample_messages())
    assert len(load_messages(json.loads(json.dumps(dumped)))) == 3


def test_load_messages_handles_empty() -> None:
    assert load_messages(None) == []
    assert load_messages([]) == []


def test_resume_uses_persisted_transcript(monkeypatch) -> None:
    monkeypatch.setattr(settings, "persist_task_transcript", True)
    task = SimpleNamespace(transcript=dump_messages(_sample_messages()), goal="launch")

    messages = NativeBackend()._resume_or_seed(task)

    assert len(messages) == 3
    assert isinstance(messages[1].content[1], ToolUseBlock)


def test_resume_seeds_fresh_without_transcript(monkeypatch) -> None:
    monkeypatch.setattr(settings, "persist_task_transcript", True)
    task = SimpleNamespace(transcript=None, goal="launch the company")

    messages = NativeBackend()._resume_or_seed(task)

    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content == "Begin: launch the company"


def test_resume_disabled_seeds_fresh(monkeypatch) -> None:
    monkeypatch.setattr(settings, "persist_task_transcript", False)
    task = SimpleNamespace(transcript=dump_messages(_sample_messages()), goal="launch")

    messages = NativeBackend()._resume_or_seed(task)

    assert len(messages) == 1
    assert messages[0].content == "Begin: launch"


def test_transcript_lines_renders_chat_log() -> None:
    lines = transcript_lines(dump_messages(_sample_messages()))

    assert lines == [
        "you: Begin: launch the company",
        "agent: Planning the launch.",
        'agent → record_metric({"name": "signups", "value": 3})',
        "tool ← ok",
    ]


def test_transcript_lines_marks_errors() -> None:
    messages = [
        Message(
            role="user",
            content=[ToolResultBlock(tool_use_id="x", content="boom", is_error=True)],
        )
    ]
    assert transcript_lines(dump_messages(messages)) == ["tool ✗ boom"]


def test_transcript_lines_keeps_only_the_last_n() -> None:
    messages = [Message(role="assistant", content=[TextBlock(text=f"step {i}")]) for i in range(80)]
    lines = transcript_lines(dump_messages(messages), limit=50)

    assert len(lines) == 50
    assert lines[0] == "agent: step 30"
    assert lines[-1] == "agent: step 79"


def test_transcript_lines_empty_when_no_transcript() -> None:
    assert transcript_lines(None) == []
    assert transcript_lines([]) == []
