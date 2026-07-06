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


#: Placeholder result injected for a tool call that was interrupted before its
#: result was recorded — see :func:`sanitize_messages`.
_INTERRUPTED_RESULT = (
    "(interrupted: this tool call did not complete and no result was recorded. "
    "Treat it as failed — retry it or take a different step.)"
)


def _tool_use_ids(message: Message) -> list[str]:
    if isinstance(message.content, list):
        return [b.id for b in message.content if isinstance(b, ToolUseBlock)]
    return []


def _tool_result_ids(message: Message | None) -> set[str]:
    if message is None or not isinstance(message.content, list):
        return set()
    return {b.tool_use_id for b in message.content if isinstance(b, ToolResultBlock)}


def sanitize_messages(messages: list[Message]) -> list[Message]:
    """Repair a resumed transcript so every ``tool_use`` has a matching ``tool_result``.

    The native loop only checkpoints at clean step boundaries, so a transcript is
    *normally* a valid resume point. But a provider can still interrupt a tool-call
    loop — a reasoning model that stops mid-stream, or a crash between executing a
    tool and persisting its result — leaving an assistant ``tool_use`` block with no
    answering ``tool_result``. Replaying that history makes the next provider call
    fail hard ("tool_use ids were found without tool_result blocks").

    This walks the turns and, for any dangling ``tool_use``, injects a placeholder
    error ``tool_result`` (DeerFlow does the same on resume): either appended to the
    following user turn when one exists, or as a synthesized user turn when the
    assistant's tool call was the very last thing recorded. The returned list is a
    valid, resumable conversation. Pure (no I/O), so it is unit-testable.
    """
    if not messages:
        return messages
    repaired: list[Message] = []
    i, n = 0, len(messages)
    while i < n:
        msg = messages[i]
        repaired.append(msg)
        use_ids = _tool_use_ids(msg)
        if msg.role == "assistant" and use_ids:
            nxt = messages[i + 1] if i + 1 < n else None
            is_result_turn = (
                nxt is not None
                and nxt.role == "user"
                and isinstance(nxt.content, list)
                and any(isinstance(b, ToolResultBlock) for b in nxt.content)
            )
            if is_result_turn:
                missing = [uid for uid in use_ids if uid not in _tool_result_ids(nxt)]
                if missing:
                    nxt.content.extend(  # type: ignore[union-attr]
                        ToolResultBlock(tool_use_id=uid, content=_INTERRUPTED_RESULT, is_error=True)
                        for uid in missing
                    )
                repaired.append(nxt)
                i += 2
                continue
            # No answering result turn at all — synthesize one for every call.
            repaired.append(
                Message(
                    role="user",
                    content=[
                        ToolResultBlock(tool_use_id=uid, content=_INTERRUPTED_RESULT, is_error=True)
                        for uid in use_ids
                    ],
                )
            )
            i += 1
            continue
        i += 1
    return repaired


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
