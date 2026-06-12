"""Agent tool registry + executor.

Tools are the ONLY way agents affect the world. Tools with real-money side
effects (e.g. ``register_domain``) declare a cost and route their charge through
the same :class:`CostMeter` chokepoint as LLM calls, so the budget, spend
breaker, per-agent caps, and governance all apply identically.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, DecisionRequest, MemoryEntry, Task
from app.models.enums import (
    AgentRole,
    DecisionKind,
    DecisionStatus,
    MemoryType,
    RunTrigger,
    TaskStatus,
)
from app.providers.base import ToolSpec
from app.runtime.breakers import loop_signature

# Simulated external vendor prices (cents). Real integrations slot in later.
DOMAIN_PRICE_CENTS = 1200


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="dispatch_task",
        description="Delegate a sub-task to another functional agent by role.",
        input_schema={
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "enum": ["growth", "research", "product", "finance", "governance"],
                },
                "goal": {"type": "string", "description": "What that agent should accomplish."},
            },
            "required": ["role", "goal"],
        },
    ),
    ToolSpec(
        name="write_memory",
        description="Record an institutional learning, decision, experiment, or result.",
        input_schema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["decision", "experiment", "result", "learning", "strategy_shift"],
                },
                "title": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["type", "title", "content"],
        },
    ),
    ToolSpec(
        name="register_domain",
        description="Purchase a domain name (incurs a real external charge).",
        input_schema={
            "type": "object",
            "properties": {"domain": {"type": "string"}},
            "required": ["domain"],
        },
    ),
    ToolSpec(
        name="request_decision",
        description="Escalate a decision to the founder. Pauses this task until they respond.",
        input_schema={
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["spend_approval", "risky_action", "strategy"],
                },
                "summary": {"type": "string"},
            },
            "required": ["kind", "summary"],
        },
    ),
    ToolSpec(
        name="report_result",
        description="Finish this task and report the outcome.",
        input_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    ),
]


@dataclass
class ToolOutcome:
    observation: str
    stop: bool = False  # report_result -> finish the task
    park: bool = False  # request_decision -> wait for founder


async def _spawn_child(db, ctx, parent: Task, agent: Agent, role: str, goal: str) -> None:
    from sqlalchemy import select

    child_agent = await db.scalar(
        select(Agent).where(Agent.company_id == parent.company_id, Agent.role == AgentRole(role))
    )
    if child_agent is None:
        return
    child = Task(
        company_id=parent.company_id,
        run_id=parent.run_id,
        root_run_id=parent.root_run_id,
        agent_id=child_agent.id,
        parent_task_id=parent.id,
        depth=parent.depth + 1,
        goal=goal,
        status=TaskStatus.queued,
        loop_signature=loop_signature(child_agent.id, goal),
    )
    db.add(child)
    await db.flush()
    await ctx.enqueue_task(child.id)


async def execute_tool(
    db: AsyncSession,
    ctx,
    *,
    agent: Agent,
    task: Task,
    name: str,
    args: dict,
) -> ToolOutcome:
    if name == "report_result":
        return ToolOutcome(observation="reported", stop=True)

    if name == "dispatch_task":
        await _spawn_child(db, ctx, task, agent, args["role"], args["goal"])
        return ToolOutcome(observation=f"dispatched {args['role']}: {args['goal'][:80]}")

    if name == "write_memory":
        db.add(
            MemoryEntry(
                company_id=task.company_id,
                type=MemoryType(args["type"]),
                title=args["title"][:500],
                content=args["content"],
                source_task_id=task.id,
            )
        )
        await db.flush()
        return ToolOutcome(observation=f"memory saved: {args['title'][:60]}")

    if name == "register_domain":
        await ctx.cost_meter.charge_external(
            company_id=task.company_id,
            agent_id=agent.id,
            task_id=task.id,
            amount_cents=DOMAIN_PRICE_CENTS,
            vendor="registrar(sim)",
            sku=args["domain"],
            description=f"domain {args['domain']}",
        )
        return ToolOutcome(observation=f"registered domain {args['domain']} (${DOMAIN_PRICE_CENTS/100:.2f})")

    if name == "request_decision":
        db.add(
            DecisionRequest(
                company_id=task.company_id,
                agent_id=agent.id,
                task_id=task.id,
                kind=DecisionKind(args["kind"]),
                summary=args["summary"],
                status=DecisionStatus.pending,
            )
        )
        task.status = TaskStatus.waiting_approval
        await db.flush()
        return ToolOutcome(observation="escalated to founder", park=True)

    return ToolOutcome(observation=f"unknown tool {name}")
