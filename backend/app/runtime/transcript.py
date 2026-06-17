"""(De)serialize a running task's working memory for durable persistence.

The native agent loop keeps its multi-turn conversation as an in-memory list of
:class:`~app.providers.base.Message` objects whose structured turns carry the
provider-agnostic content blocks (text / tool_use / tool_result). To survive a
process restart, that list is checkpointed to ``Task.transcript`` (JSONB) after
every completed step and replayed on resume.

These helpers are the single source of truth for that wire shape. They are pure
(no I/O), so the round-trip is unit-testable without a database, and they keep
the JSON tagging in one place rather than scattered through the backend.
"""

from __future__ import annotations

import json
from typing import Any

from app.providers.base import (
    ContentBlock,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def _dump_block(block: ContentBlock) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    raise TypeError(f"unserializable content block: {type(block).__name__}")


def _load_block(data: dict[str, Any]) -> ContentBlock:
    kind = data.get("type")
    if kind == "text":
        return TextBlock(text=data["text"])
    if kind == "tool_use":
        return ToolUseBlock(id=data["id"], name=data["name"], input=data["input"])
    if kind == "tool_result":
        return ToolResultBlock(
            tool_use_id=data["tool_use_id"],
            content=data["content"],
            is_error=data.get("is_error", False),
        )
    raise ValueError(f"unknown content block type: {kind!r}")


def dump_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Serialize a message list to JSON-able dicts for ``Task.transcript``."""
    out: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message.content, str):
            content: Any = message.content
        else:
            content = [_dump_block(block) for block in message.content]
        out.append({"role": message.role, "content": content})
    return out


def load_messages(data: list[dict[str, Any]] | None) -> list[Message]:
    """Rebuild a message list from a persisted ``Task.transcript`` (or ``None``)."""
    if not data:
        return []
    messages: list[Message] = []
    for item in data:
        content = item["content"]
        if isinstance(content, list):
            content = [_load_block(block) for block in content]
        messages.append(Message(role=item["role"], content=content))
    return messages


def _clip(text: str, limit: int = 240) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _block_lines(speaker: str, block: ContentBlock) -> list[str]:
    if isinstance(block, TextBlock):
        return [f"{speaker}: {line}" for line in block.text.strip().splitlines() if line.strip()]
    if isinstance(block, ToolUseBlock):
        args = json.dumps(block.input, ensure_ascii=False)
        return [f"agent → {block.name}({_clip(args)})"]
    if isinstance(block, ToolResultBlock):
        tag = "tool ✗" if block.is_error else "tool ←"
        return [f"{tag} {_clip(block.content.replace(chr(10), ' '))}"]
    return []


def transcript_lines(data: list[dict[str, Any]] | None, limit: int = 50) -> list[str]:
    """Render a persisted transcript into the last ``limit`` human-readable lines.

    A flat, chat-log view for the task detail screen: user/agent text turns, the
    tools the agent invoked (with compact arguments), and each tool's result.
    Long values are clipped. Returns at most ``limit`` lines (the most recent),
    or an empty list when there is no transcript (e.g. a finished task, whose
    working memory has been cleared).
    """
    lines: list[str] = []
    for message in load_messages(data):
        speaker = "agent" if message.role == "assistant" else "you"
        if isinstance(message.content, str):
            lines.extend(
                f"{speaker}: {line}" for line in message.content.strip().splitlines() if line.strip()
            )
        else:
            for block in message.content:
                lines.extend(_block_lines(speaker, block))
    return lines[-limit:] if limit and limit > 0 else lines
