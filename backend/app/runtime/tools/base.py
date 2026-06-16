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


#: Every tool handler is an async callable returning a :class:`ToolOutcome`.
Handler = Callable[..., Awaitable[ToolOutcome]]
__all__ = ["ToolOutcome", "Handler", "Any", "consume_approval_grant"]
