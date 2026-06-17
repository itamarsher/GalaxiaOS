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
