"""Core agent tools: delegation, memory, metrics, web search, comms, control.

These are the universal tools every agent has regardless of business area. The
area-specific tools (sales/marketing/ops/finance/legal) live in sibling modules.
"""

from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.integrations.base import RegistrarError
from app.integrations.registry import get_registrar
from app.integrations.websearch import WebSearchError, get_web_search
from app.models import Agent, DecisionRequest, Task
from app.models.enums import (
    AgentRole,
    DecisionKind,
    DecisionStatus,
    MemoryType,
    MetricSource,
    TaskStatus,
)
from app.providers.base import ToolSpec
from app.runtime.breakers import loop_signature
from app.runtime.tools.base import ToolOutcome
from app.services import metrics as metrics_svc

SPECS: list[ToolSpec] = [
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
        description=(
            "Register a domain name. Checks availability and price first; only "
            "available domains incur a real external charge, billed at the "
            "registrar's quoted price."
        ),
        input_schema={
            "type": "object",
            "properties": {"domain": {"type": "string"}},
            "required": ["domain"],
        },
    ),
    ToolSpec(
        name="send_email",
        description=(
            "Send an email (sales outreach, marketing, ops, or support). Uses the "
            "configured email provider; off-by-default simulated unless SMTP is set."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address."},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
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
    ToolSpec(
        name="read_metrics",
        description="Read the most recent real-world business metrics for the company.",
        input_schema={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name="record_metric",
        description="Record one observed real-world outcome signal (a measured metric).",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "value": {"type": "number"},
                "unit": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["name", "value"],
        },
    ),
    ToolSpec(
        name="web_search",
        description="Search the web for up-to-date external information.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="collect_results",
        description=(
            "Gather the outputs of sub-tasks you dispatched earlier that have "
            "finished, so you can synthesize their results."
        ),
        input_schema={"type": "object", "properties": {}},
    ),
]


async def _spawn_child(db, ctx, parent: Task, agent: Agent, role: str, goal: str) -> None:
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


async def _dispatch_task(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    await _spawn_child(db, ctx, task, agent, args["role"], args["goal"])
    return ToolOutcome(observation=f"dispatched {args['role']}: {args['goal'][:80]}")


async def _write_memory(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    from app.services import memory as memory_svc

    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType(args["type"]),
        title=args["title"],
        content=args["content"],
        source_task_id=task.id,
    )
    return ToolOutcome(observation=f"memory saved: {args['title'][:60]}")


async def _register_domain(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    domain = args["domain"]
    registrar = get_registrar()
    quote = await registrar.check(domain)
    if not quote.available:
        # No charge: nothing was reserved or spent.
        return ToolOutcome(observation=f"domain {domain} unavailable; not registered (no charge)")

    async def _do_register() -> tuple[int, str | None, dict | None]:
        reg = await registrar.register(domain)
        return reg.price_cents, reg.external_ref, {"domain": domain}

    try:
        ref = await ctx.cost_meter.metered_external(
            company_id=task.company_id,
            agent_id=agent.id,
            task_id=task.id,
            estimated_cents=quote.price_cents,
            vendor=f"registrar({settings.domain_registrar})",
            sku=domain,
            action=_do_register,
            description=f"domain {domain}",
        )
    except RegistrarError as exc:
        return ToolOutcome(observation=f"domain {domain} registration failed: {exc}", is_error=True)
    return ToolOutcome(
        observation=f"registered domain {domain} (${quote.price_cents / 100:.2f}, ref {ref})"
    )


async def _send_email(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    from app.integrations.email import EmailError, get_email_sender
    from app.services import memory as memory_svc

    try:
        res = await get_email_sender().send(
            to=args["to"], subject=args["subject"], body=args["body"]
        )
    except EmailError as exc:
        return ToolOutcome(observation=f"email send failed: {exc}", is_error=True)
    # Log the outbound communication for auditability / recall.
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title=f"Email to {args['to']}: {args['subject'][:80]}",
        content=args["body"][:2000],
        source_task_id=task.id,
    )
    return ToolOutcome(
        observation=(
            f"email sent to {args['to']} via {res.provider} "
            f"(subject {args['subject'][:60]!r}, id {res.message_id})"
        )
    )


async def _read_metrics(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    signals = await metrics_svc.latest_signals(
        db, company_id=task.company_id, limit=settings.metrics_recall_limit
    )
    return ToolOutcome(observation=metrics_svc.summarize_for_prompt(signals))


async def _record_metric(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    await metrics_svc.record_signal(
        db,
        company_id=task.company_id,
        name=args["name"],
        value=float(args["value"]),
        unit=args.get("unit"),
        source=MetricSource.agent,
        note=args.get("note"),
    )
    unit = f" {args['unit']}" if args.get("unit") else ""
    return ToolOutcome(observation=f"recorded metric {args['name']}={float(args['value']):g}{unit}")


async def _web_search(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    try:
        results = await get_web_search().search(
            args["query"], max_results=settings.web_search_max_results
        )
    except WebSearchError as exc:
        return ToolOutcome(observation=f"web search failed: {exc}", is_error=True)
    if not results:
        return ToolOutcome(observation=f"no web results for {args['query']!r}")
    lines = [f"- {r.title} ({r.url})\n  {r.snippet[:200]}" for r in results]
    observation = f"Web results for {args['query']!r}:\n" + "\n".join(lines)
    return ToolOutcome(observation=observation[:2000])


async def _collect_results(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    rows = (
        await db.scalars(
            select(Task)
            .where(Task.parent_task_id == task.id, Task.status == TaskStatus.done)
            .order_by(Task.created_at.asc())
        )
    ).all()
    if not rows:
        return ToolOutcome(observation="No dispatched sub-tasks have finished yet.")
    lines = []
    for child in rows:
        summary = (child.output or {}).get("summary", "") if child.output else ""
        lines.append(f"- {child.goal[:80]}: {summary[:300] or '(no summary)'}")
    observation = "Completed sub-task results:\n" + "\n".join(lines)
    return ToolOutcome(observation=observation[:2000])


async def _request_decision(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
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
    # ``task`` is detached from this session (it was loaded in the worker's
    # session, which has since closed), so mutating it directly would never be
    # persisted — leaving the task stuck in ``running`` even though it's parked.
    # Re-fetch the live row so the ``waiting_approval`` status actually commits.
    row = await db.get(Task, task.id)
    if row is not None:
        row.status = TaskStatus.waiting_approval
    task.status = TaskStatus.waiting_approval  # keep the in-memory copy consistent
    await db.flush()
    return ToolOutcome(observation="escalated to founder", park=True)


async def _report_result(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return ToolOutcome(observation="reported", stop=True)


HANDLERS = {
    "dispatch_task": _dispatch_task,
    "write_memory": _write_memory,
    "register_domain": _register_domain,
    "send_email": _send_email,
    "request_decision": _request_decision,
    "report_result": _report_result,
    "read_metrics": _read_metrics,
    "record_metric": _record_metric,
    "web_search": _web_search,
    "collect_results": _collect_results,
}
