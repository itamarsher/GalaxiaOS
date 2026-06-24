"""Shared types for the agent tool registry.

Tools live in per-area modules in this package (``core``, ``sales``,
``marketing``, ``ops``, ``finance``, ``legal``). Each module exposes a
``SPECS: list[ToolSpec]`` and a ``HANDLERS: dict[str, Handler]``; the package
``__init__`` auto-discovers them, so adding a tool is just dropping a function
into the right module — no central registry edits.

Every handler has the same signature::

    async def handler(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome

and tools remain the ONLY way agents affect the world. Tools with real-money
side effects must route their charge through ``ctx.cost_meter`` (same chokepoint
as LLM calls) and put the spend amount in ``args["amount_cents"]`` so governance
and the spend breaker gate them up front.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.models import DecisionRequest
from app.models.enums import DecisionStatus


@dataclass
class ToolOutcome:
    observation: str
    stop: bool = False  # report_result -> finish the task
    park: bool = False  # request_decision -> wait for founder
    is_error: bool = False  # surfaced as a tool_result error block to the model


async def consume_approval_grant(db, *, task_id: uuid.UUID, tool: str) -> bool:
    """Use up a founder approval for ``tool`` on this task, if one is pending.

    When the founder approves a gated action the task is re-queued and re-run
    from the top; without this, the same gate (governance, budget, or plan) would
    just re-trigger and ask for approval again forever. An approved
    :class:`DecisionRequest` therefore acts as a one-shot grant: the first
    matching tool call on resume consumes it and proceeds instead of escalating
    again. Shared by the native backend (governance/budget gates) and the
    plan-approval gate so the resume semantics are identical everywhere.
    """
    grants = (
        await db.scalars(
            select(DecisionRequest).where(
                DecisionRequest.task_id == task_id,
                DecisionRequest.status == DecisionStatus.approved,
            )
        )
    ).all()
    for grant in grants:
        payload = grant.payload or {}
        if payload.get("tool") == tool and not payload.get("consumed"):
            grant.payload = {**payload, "consumed": True}
            await db.flush()
            return True
    return False


def truncation_notice(omitted: int, unit: str = "characters") -> str:
    """The marker appended to any output we had to cut short.

    Phrased so the receiving agent treats the content as incomplete (and, where it
    can, fetches the rest or narrows its request) instead of mistaking a partial
    result for the whole.
    """
    return (
        f"\n\n[… truncated: {omitted} more {unit} omitted. This output is INCOMPLETE — "
        "do not treat it as the full content.]"
    )


def clip(text: str | None, limit: int, *, unit: str = "characters") -> str:
    """Truncate ``text`` to ``limit`` chars, flagging it ONLY when actually cut.

    Returns the text unchanged (no marker) when it already fits, so an agent never
    sees a spurious "truncated" note; appends :func:`truncation_notice` when content
    was genuinely dropped. Use everywhere output handed back to an agent is length-
    capped, so a clipped result is always self-describing.
    """
    if not text:
        return text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + truncation_notice(len(text) - limit, unit)


def unsupported_capability(capability: str, *, hint: str | None = None) -> ToolOutcome:
    """Standard outcome for a tool that has no real backing provider.

    Returned *instead* of a fabricated/simulated success so an agent never mistakes
    a stubbed action for a real one. Faking success here is what poisons the loop:
    a phantom result gets written to Company Memory and the metrics, then feeds back
    into planning prompts, so agents confidently plan around leads/customers/spend
    that never existed. This outcome is an explicit error and points the agent at the
    built-in escalation path — ``request_capability`` — so a genuine gap becomes a
    tracked platform request rather than a hallucination.
    """
    message = (
        f"{capability} is not supported in this environment: it is not connected to a "
        "real provider, so NOTHING happened — nothing was sent, logged, published, "
        "created, or charged. Do not record or assume any result. If you need this to "
        "do your job, call `request_capability` with a clear title and details so the "
        "Platform agent can add it."
    )
    if hint:
        message = f"{message} {hint}"
    return ToolOutcome(observation=message, is_error=True)


#: Every tool handler is an async callable returning a :class:`ToolOutcome`.
Handler = Callable[..., Awaitable[ToolOutcome]]
__all__ = [
    "ToolOutcome",
    "Handler",
    "Any",
    "consume_approval_grant",
    "unsupported_capability",
    "clip",
    "truncation_notice",
]
