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
from app.models import Agent, Budget, DecisionRequest, Task
from app.models.enums import (
    AgentRole,
    AgentStatus,
    BudgetPeriod,
    DecisionKind,
    DecisionStatus,
    MemoryType,
    MetricSource,
    TaskStatus,
)
from app.providers.base import ToolSpec
from app.runtime.breakers import loop_signature
from app.runtime.tools.base import ToolOutcome, consume_approval_grant
from app.services import metrics as metrics_svc

SPECS: list[ToolSpec] = [
    ToolSpec(
        name="submit_plan",
        description=(
            "CEO only. Submit your high-level execution plan to the founder for "
            "approval BEFORE dispatching any work. The task pauses until the "
            "founder approves; once approved, proceed to dispatch the initiatives."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": (
                        "The plan, written in Markdown: for each objective, a "
                        "subheading and a short bulleted list of the 1-3 concrete "
                        "initiatives you intend to pursue and which agent owns each."
                    ),
                }
            },
            "required": ["plan"],
        },
    ),
    ToolSpec(
        name="request_budget",
        description=(
            "Request budget headroom for an upcoming spend. If the amount fits "
            "within the company's remaining monthly budget the CEO approves it "
            "automatically; if it would go over budget it is escalated to the "
            "founder as a decision (who can authorise additional funds). Use this "
            "before a large external charge so you know whether you're cleared to spend."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "amount_cents": {
                    "type": "integer",
                    "description": "Amount you want to spend, in cents.",
                },
                "reason": {
                    "type": "string",
                    "description": "What the budget is for.",
                },
            },
            "required": ["amount_cents", "reason"],
        },
    ),
    ToolSpec(
        name="dispatch_task",
        description="Delegate a sub-task to another functional agent by role.",
        input_schema={
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "enum": ["growth", "research", "product", "finance", "governance", "auditor", "data"],
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
                "summary": {
                    "type": "string",
                    "description": (
                        "What you need decided, written in Markdown. Use a short "
                        "**bold** headline, then concise bullets for the context, "
                        "options, and your recommendation so the founder can scan it."
                    ),
                },
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
    # Prefer an active agent of the role: paused agents are parked (their work is
    # blocked anyway), and after the CEO hires extra capacity there may be more
    # than one — dispatch to the earliest-created active one for determinism.
    child_agent = await db.scalar(
        select(Agent)
        .where(
            Agent.company_id == parent.company_id,
            Agent.role == AgentRole(role),
            Agent.status == AgentStatus.active,
        )
        .order_by(Agent.created_at)
        .limit(1)
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


async def _plan_is_approved(db, task_id) -> bool:
    """True once the founder has approved this task's plan (a plan_approval grant)."""
    return (
        await db.scalar(
            select(DecisionRequest.id).where(
                DecisionRequest.task_id == task_id,
                DecisionRequest.kind == DecisionKind.plan_approval,
                DecisionRequest.status == DecisionStatus.approved,
            )
        )
    ) is not None


async def _dispatch_task(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    # Plan-approval gate: on a launch run the CEO must get the founder's sign-off
    # on the plan before any functional work is dispatched. Other runs (scheduled
    # business cycles, sub-tasks) carry no flag and dispatch freely.
    if (task.input or {}).get("requires_plan_approval") and not await _plan_is_approved(
        db, task.id
    ):
        return ToolOutcome(
            observation=(
                "Hold on — the founder hasn't approved the plan yet. Call "
                "`submit_plan` with your proposed execution plan and wait for "
                "approval before dispatching any work."
            ),
            is_error=True,
        )
    await _spawn_child(db, ctx, task, agent, args["role"], args["goal"])
    return ToolOutcome(observation=f"dispatched {args['role']}: {args['goal'][:80]}")


async def _submit_plan(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    plan = str(args["plan"]).strip()
    # On resume after approval, a one-shot grant lets the CEO proceed instead of
    # re-submitting the same plan forever.
    if await consume_approval_grant(db, task_id=task.id, tool="submit_plan"):
        return ToolOutcome(
            observation=(
                "The founder approved your plan. Proceed now: dispatch the "
                "initiatives to the functional agents."
            )
        )
    db.add(
        DecisionRequest(
            company_id=task.company_id,
            agent_id=agent.id,
            task_id=task.id,
            kind=DecisionKind.plan_approval,
            summary=f"Proposed execution plan:\n\n{plan}",
            payload={"tool": "submit_plan", "plan": plan},
            status=DecisionStatus.pending,
        )
    )
    row = await db.get(Task, task.id)
    if row is not None:
        row.status = TaskStatus.waiting_approval
    task.status = TaskStatus.waiting_approval  # keep the in-memory copy consistent
    await db.flush()
    return ToolOutcome(observation="submitted plan to the founder for approval", park=True)


async def _request_budget(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    amount_cents = int(args["amount_cents"])
    reason = str(args.get("reason") or "").strip()
    budget = await db.scalar(
        select(Budget).where(
            Budget.company_id == task.company_id, Budget.period == BudgetPeriod.monthly
        )
    )
    remaining = (
        int(budget.limit_cents) - int(budget.spent_cents) - int(budget.reserved_cents)
        if budget is not None
        else 0
    )
    if amount_cents <= 0:
        return ToolOutcome(observation="Budget request must be a positive amount.", is_error=True)

    # Within the budget the founder already set → the CEO approves it; no need to
    # bother the founder.
    if amount_cents <= remaining:
        return ToolOutcome(
            observation=(
                f"Approved by the CEO: ${amount_cents / 100:.2f} for {reason or 'this spend'} "
                f"fits within the remaining monthly budget (${remaining / 100:.2f} left). "
                "You're cleared to spend."
            )
        )

    # Over budget → escalate to the founder. Approving lifts the cap by the
    # shortfall so the spend can go through (payment is wired in separately).
    shortfall = amount_cents - max(0, remaining)
    db.add(
        DecisionRequest(
            company_id=task.company_id,
            agent_id=agent.id,
            task_id=task.id,
            kind=DecisionKind.spend_approval,
            summary=(
                f"**Budget request — over budget**\n\n"
                f"**${amount_cents / 100:.2f}** requested for {reason or 'an upcoming spend'}, "
                f"but only **${max(0, remaining) / 100:.2f}** is left this month.\n\n"
                f"Approve to add **${shortfall / 100:.2f}** of headroom."
            ),
            payload={
                "tool": "request_budget",
                "reason": reason,
                "requested_cents": amount_cents,
                "available_cents": max(0, remaining),
                "budget_increase_cents": shortfall,
            },
            status=DecisionStatus.pending,
        )
    )
    row = await db.get(Task, task.id)
    if row is not None:
        row.status = TaskStatus.waiting_approval
    task.status = TaskStatus.waiting_approval
    await db.flush()
    return ToolOutcome(
        observation="Over budget — escalated to the founder to authorise the extra funds.",
        park=True,
    )


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


#: Provider name under which a company's web-search (Tavily) key is stored (BYOK).
WEB_SEARCH_PROVIDER = "tavily"


async def _resolve_web_search(db, company_id) -> tuple[object, int]:
    """Return ``(provider, cost_cents)`` for this company's web search.

    A founder can attach a Tavily key per company (onboarding or Settings); with
    one we run real, billable web search. Without it we fall back to the
    configured default — offline ``simulated`` (free, ``cost_cents == 0``) unless
    the deployment set a global real provider. The returned ``cost_cents`` is the
    *estimate* the CostMeter reserves up front (``web_search_cost_cents`` per
    expected credit; advanced depth assumes two credits). The committed actual is
    reconciled afterwards from the credits Tavily reports per call — see
    :func:`_web_search`.
    """
    from app.integrations.websearch import SimulatedWebSearch
    from app.services import apikeys

    key = await apikeys.get_plaintext_key(
        db, company_id=company_id, provider=WEB_SEARCH_PROVIDER
    )
    if key:
        from app.integrations.tavily import TavilyWebSearch

        search: object = TavilyWebSearch(api_key=key)
    else:
        search = get_web_search()

    if isinstance(search, SimulatedWebSearch):
        return search, 0
    multiplier = 2 if settings.tavily_search_depth == "advanced" else 1
    return search, settings.web_search_cost_cents * multiplier


async def _web_search(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    query = args["query"]
    search, cost_cents = await _resolve_web_search(db, task.company_id)
    try:
        if cost_cents > 0:
            # Real (paid) provider: reserve the estimated cost first, run the
            # search, then commit the *measured* spend — same chokepoint and
            # budget gating as LLM calls and domain purchases. An over-budget
            # search raises BudgetExceeded, which the backend escalates to the
            # founder. Tavily reports the credits each call consumed (basic=1,
            # advanced=2) but no dollar figure, so we reconcile the actual charge
            # as ``credits × web_search_cost_cents`` and fall back to the reserved
            # estimate when usage telemetry is unavailable.
            captured: dict = {}

            async def _do() -> tuple[int, str | None, dict | None]:
                hits = await search.search(query, max_results=settings.web_search_max_results)
                captured["results"] = hits
                credits = getattr(search, "last_usage_credits", None)
                actual_cents = (
                    credits * settings.web_search_cost_cents
                    if credits is not None
                    else cost_cents
                )
                request_id = getattr(search, "last_request_id", None)
                return (
                    actual_cents,
                    request_id,
                    {"query": query, "results": len(hits), "credits": credits},
                )

            await ctx.cost_meter.metered_external(
                company_id=task.company_id,
                agent_id=agent.id,
                task_id=task.id,
                estimated_cents=cost_cents,
                vendor=f"web_search({settings.web_search_provider})",
                sku=query[:120],
                action=_do,
                description=f"web search: {query[:80]}",
            )
            results = captured.get("results", [])
        else:
            results = await search.search(query, max_results=settings.web_search_max_results)
    except WebSearchError as exc:
        return ToolOutcome(observation=f"web search failed: {exc}", is_error=True)
    if not results:
        return ToolOutcome(observation=f"no web results for {query!r}")
    lines = [f"- {r.title} ({r.url})\n  {r.snippet[:200]}" for r in results]
    observation = f"Web results for {query!r}:\n" + "\n".join(lines)
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
    "submit_plan": _submit_plan,
    "request_budget": _request_budget,
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
