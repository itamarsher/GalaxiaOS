"""Core agent tools: delegation, memory, metrics, web search, comms, control.

These are the universal tools every agent has regardless of business area. The
area-specific tools (sales/marketing/ops/finance/legal) live in sibling modules.
"""

from __future__ import annotations

import uuid

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
from app.runtime.tools.base import (
    ToolOutcome,
    clip,
    consume_approval_grant,
    unsupported_capability,
)
from app.services import chat
from app.services import metrics as metrics_svc
from app.services import objectives as objectives_svc

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
        name="request_secret",
        description=(
            "Request a secret you need to do your work but must never see — a "
            "third-party API key, a password, an access token. This escalates to the "
            "founder, who provides the value through a secure channel; it is encrypted "
            "at rest and you are NEVER given the raw value. Once provided, use it by "
            "putting the placeholder {{secret:NAME}} in the relevant tool argument (a "
            "request header, URL, or body) — it is substituted at the network boundary "
            "and redacted from logs. Call this when a capability needs a credential the "
            "company hasn't supplied yet. The task pauses until the founder responds."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "A short handle for the secret, referenced later as "
                        "{{secret:NAME}} — e.g. 'stripe_api_key', 'smtp_password'."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "What you need it for, so the founder knows what they're providing.",
                },
                "allowed_host": {
                    "type": "string",
                    "description": (
                        "Optional. The hostname this secret is allowed to be sent to "
                        "(e.g. 'api.stripe.com'), binding it to that destination."
                    ),
                },
            },
            "required": ["name", "reason"],
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
                    "enum": [
                        "growth",
                        "research",
                        "product",
                        "design",
                        "finance",
                        "governance",
                        "auditor",
                        "data",
                    ],
                },
                "goal": {"type": "string", "description": "What that agent should accomplish."},
                "objective": {
                    "type": "integer",
                    "description": (
                        "REQUIRED: the number of the company objective this initiative "
                        "advances (from the objectives list in your briefing). This links "
                        "the work to the objective so the founder sees real progress."
                    ),
                },
            },
            "required": ["role", "goal", "objective"],
        },
    ),
    ToolSpec(
        name="dispatch_tasks",
        description=(
            "Delegate SEVERAL sub-tasks at once — they run in PARALLEL. Prefer this "
            "over multiple separate dispatch_task calls whenever the initiatives are "
            "independent: the run finishes sooner. Use collect_results to converge."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {
                                "type": "string",
                                "enum": [
                                    "growth",
                                    "research",
                                    "product",
                                    "design",
                                    "finance",
                                    "governance",
                                    "auditor",
                                    "data",
                                ],
                            },
                            "goal": {
                                "type": "string",
                                "description": "What that agent should accomplish.",
                            },
                            "objective": {
                                "type": "integer",
                                "description": (
                                    "REQUIRED: number of the company objective this initiative "
                                    "advances (from your briefing)."
                                ),
                            },
                        },
                        "required": ["role", "goal", "objective"],
                    },
                }
            },
            "required": ["tasks"],
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
        description=(
            "Escalate a founder/board-level decision to the founder — a risky or irreversible "
            "external action, or a genuine strategic pivot. Pauses this task until they respond. "
            "Do NOT use this for operational blockers, missing inputs, or work another agent owns "
            "or is producing (e.g. a deliverable being made in parallel): the founder is a board "
            "member, not an operator — take those to the CEO or the owning teammate with "
            "`message_teammate` instead."
        ),
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
        name="request_user_action",
        description=(
            "Ask the founder to perform a real-world action you cannot do through any "
            "tool — something only a human can carry out (e.g. make a phone call, sign "
            "up for an account, inspect something offline, confirm an external result) — "
            "and report back. This pauses your task until they respond; their reported "
            "results come back to you so you can continue with them. Use this instead of "
            "guessing an outcome or giving up when the only path forward needs a person. "
            "NEVER use this to obtain an API key, token, password, or any other secret — "
            "the reply would be exposed in plaintext; use `request_secret` for those."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "The concrete action you need the founder to perform, written so "
                        "they know exactly what to do and what result to report back."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "Why you need this action and how the result unblocks your task.",
                },
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name="post_mission_update",
        description=(
            "Post a short, founder-facing update to the live Mission Log when you "
            "hit a SIGNIFICANT milestone — starting a major piece of work, a "
            "notable result or turning point, or a meaningful change of plan. These "
            "are ephemeral status beats shown live on the founder's dashboard (the "
            "last few are kept, then they roll off) — post the moments that matter, "
            "not routine steps. This does NOT finish your task; keep working after."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "headline": {
                    "type": "string",
                    "description": (
                        "One concise, plain-language line the founder can scan, e.g. "
                        "'Launched cold-outreach to 40 prospects' or 'Landed first 3 leads'."
                    ),
                },
                "detail": {
                    "type": "string",
                    "description": "Optional one-sentence elaboration for context.",
                },
            },
            "required": ["headline"],
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
        name="web_fetch",
        description=(
            "Fetch the full main text content of one or more specific web pages you "
            "already have the URLs for. Use this to READ a page (a competitor's "
            "pricing page, a docs page, an article) end-to-end — `web_search` only "
            "returns short snippets, so reach for `web_fetch` when a snippet isn't "
            "enough and you need the actual page body. Pass a single `url` or a `urls` "
            "list; each page's extracted text is returned, labelled by URL. Uses the "
            "same web provider as web_search and is metered the same way."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "A single page URL to fetch."},
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Several page URLs to fetch in one call.",
                },
            },
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


# Outcomes of a dispatch attempt (``_spawn_child``), so callers can distinguish a
# missing role from a de-duplicated (already-in-flight) initiative.
_DISPATCHED = "dispatched"
_NO_AGENT = "no_agent"
_DUPLICATE = "duplicate"


def _normalized_goal(goal: str) -> str:
    """Whitespace/case-normalized goal text for duplicate detection."""
    return " ".join((goal or "").split()).lower()


async def _spawn_child(
    db,
    ctx,
    parent: Task,
    agent: Agent,
    role: str,
    goal: str,
    objective_id: uuid.UUID | None = None,
) -> str:
    """Enqueue a sub-task for the earliest active agent of ``role``.

    Returns one of :data:`_DISPATCHED`, :data:`_NO_AGENT` (no active agent of that
    role — callers surface this as a loud error rather than silently dropping the
    initiative), or :data:`_DUPLICATE` (a matching initiative is already in flight,
    so this one is skipped instead of doubling the work).
    """
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
        return _NO_AGENT
    # The dispatcher's chosen objective, else inherit the parent's — so an
    # initiative's whole sub-tree stays linked to the objective it serves.
    effective_objective = objective_id if objective_id is not None else parent.objective_id
    # Dedup: don't dispatch a second initiative that duplicates one already in flight.
    # The CEO re-plans from scratch every business cycle and can re-derive work that's
    # still running — which is how two tasks ended up publishing the same landing page.
    # Skip when an in-flight sibling has the same (normalized) goal, OR is the same
    # role working the same objective. This catches re-derived/paraphrased duplicates
    # without blocking legitimate cross-role fan-out on one objective.
    norm = _normalized_goal(goal)
    inflight = (
        await db.scalars(
            select(Task).where(
                Task.company_id == parent.company_id,
                Task.status.in_(_IN_FLIGHT),
                Task.id != parent.id,
            )
        )
    ).all()
    for other in inflight:
        same_goal = _normalized_goal(other.goal) == norm
        same_slot = (
            effective_objective is not None
            and other.objective_id == effective_objective
            and other.agent_id == child_agent.id
        )
        if same_goal or same_slot:
            return _DUPLICATE
    child = Task(
        company_id=parent.company_id,
        run_id=parent.run_id,
        root_run_id=parent.root_run_id,
        agent_id=child_agent.id,
        parent_task_id=parent.id,
        objective_id=effective_objective,
        depth=parent.depth + 1,
        goal=goal,
        status=TaskStatus.queued,
        loop_signature=loop_signature(child_agent.id, goal),
    )
    db.add(child)
    await db.flush()
    await ctx.enqueue_task(child.id)
    return _DISPATCHED


# Sentinel: a dispatch that must be objective-tagged but resolved to nothing.
_MISSING_OBJECTIVE = object()

_OBJECTIVE_REQUIRED = (
    "Every initiative must be tagged with the objective it advances. Set `objective` "
    "to the number of the relevant objective from your briefing's objectives list, "
    "then dispatch again."
)


async def _resolve_dispatch_objective(db, task: Task, handle: object) -> object:
    """The objective a dispatched task should carry: the dispatcher's chosen handle,
    else the dispatching task's own objective (so sub-delegation stays linked).

    Returns the objective id, or ``None`` when the company has no objectives yet (an
    untagged task is fine then), or :data:`_MISSING_OBJECTIVE` when objectives DO
    exist but this dispatch named none — the caller turns that into a retry prompt.
    """
    objective_id = await objectives_svc.resolve_objective_id(db, task.company_id, handle)
    if objective_id is None:
        objective_id = task.objective_id  # inherit from the dispatching task
    if objective_id is None and await objectives_svc.has_objectives(db, task.company_id):
        return _MISSING_OBJECTIVE
    return objective_id


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


async def _ancestor_has_approved_plan(db, task: Task) -> bool:
    """Whether an ANCESTOR of ``task`` already has a founder-approved plan.

    A task that descends from an approved plan exists *because* the founder signed
    off on the plan that dispatched it — it's an initiative to execute, not a plan
    to re-propose. Walks up ``parent_task_id`` (bounded; task trees are shallow).
    """
    parent_id = task.parent_task_id
    seen = 0
    while parent_id is not None and seen < 20:
        seen += 1
        if await _plan_is_approved(db, parent_id):
            return True
        parent = await db.get(Task, parent_id)
        parent_id = parent.parent_task_id if parent is not None else None
    return False


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
    objective_id = await _resolve_dispatch_objective(db, task, args.get("objective"))
    if objective_id is _MISSING_OBJECTIVE:
        return ToolOutcome(observation=_OBJECTIVE_REQUIRED, is_error=True)
    result = await _spawn_child(db, ctx, task, agent, args["role"], args["goal"], objective_id)
    if result == _NO_AGENT:
        return ToolOutcome(
            observation=(
                f"No active '{args['role']}' agent exists in this company — the "
                "initiative was NOT dispatched. Call list_team to see the roles "
                "actually available, then replan against your real roster."
            ),
            is_error=True,
        )
    if result == _DUPLICATE:
        return ToolOutcome(
            observation=(
                f"Not dispatched — a matching initiative for '{args['goal'][:60]}' is "
                "already in flight. Don't re-create work that's already running; use "
                "collect_results to check on it instead."
            )
        )
    return ToolOutcome(observation=f"dispatched {args['role']}: {args['goal'][:80]}")


async def _dispatch_tasks(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    """Fan out several sub-tasks at once; each is enqueued and runs in parallel."""
    if (task.input or {}).get("requires_plan_approval") and not await _plan_is_approved(
        db, task.id
    ):
        return ToolOutcome(
            observation=(
                "Hold on — the founder hasn't approved the plan yet. Call `submit_plan` "
                "and wait for approval before dispatching any work."
            ),
            is_error=True,
        )
    entries = args.get("tasks")
    if not isinstance(entries, list) or not entries:
        return ToolOutcome(
            observation="dispatch_tasks needs a non-empty 'tasks' list of {role, goal}.",
            is_error=True,
        )
    # Resolve every entry's objective first so the whole batch is all-or-nothing:
    # if any initiative can't be tagged, reject without dispatching a partial set.
    resolved: list[tuple[dict, object]] = []
    untagged: list[int] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or "role" not in entry or "goal" not in entry:
            continue
        objective_id = await _resolve_dispatch_objective(db, task, entry.get("objective"))
        if objective_id is _MISSING_OBJECTIVE:
            untagged.append(i + 1)
        resolved.append((entry, objective_id))
    if untagged:
        return ToolOutcome(
            observation=(f"{_OBJECTIVE_REQUIRED} Missing on task(s): {untagged} (1-based)."),
            is_error=True,
        )
    if not resolved:
        return ToolOutcome(
            observation="No valid {role, goal} entries in 'tasks'; nothing dispatched.",
            is_error=True,
        )
    dispatched: list[str] = []
    missing_roles: set[str] = set()
    duplicates: list[str] = []
    for entry, objective_id in resolved:
        result = await _spawn_child(db, ctx, task, agent, entry["role"], entry["goal"], objective_id)
        if result == _DISPATCHED:
            dispatched.append(f"{entry['role']}: {str(entry['goal'])[:60]}")
        elif result == _DUPLICATE:
            duplicates.append(f"{entry['role']}: {str(entry['goal'])[:60]}")
        else:
            missing_roles.add(entry["role"])
    lines = []
    if dispatched:
        body = "\n".join(f"- {d}" for d in dispatched)
        lines.append(f"dispatched {len(dispatched)} sub-tasks in parallel:\n{body}")
    if duplicates:
        body = "\n".join(f"- {d}" for d in duplicates)
        lines.append(
            f"Skipped {len(duplicates)} initiative(s) already in flight (not "
            f"re-dispatched):\n{body}"
        )
    if missing_roles:
        roles = ", ".join(sorted(missing_roles))
        lines.append(
            f"No active agent for role(s): {roles} — those initiatives were NOT "
            "dispatched. Call list_team to see the roles actually available, then "
            "replan against your real roster."
        )
    return ToolOutcome(observation="\n\n".join(lines), is_error=bool(missing_roles))


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
    # Don't re-plan an already-approved plan. If an ANCESTOR task already has the
    # founder's plan sign-off, this task is one of that plan's initiatives — it
    # should EXECUTE, not propose a new plan. Without this guard an execution
    # sub-task that hits a wall (e.g. a missing tool) re-submits its parent's whole
    # objective as a fresh plan_approval, burying the founder in redundant decisions
    # for work they already approved (the "repeated decisions" incident).
    if task.parent_task_id is not None and await _ancestor_has_approved_plan(db, task):
        return ToolOutcome(
            observation=(
                "The plan that created this task was already approved by the founder "
                "— you're executing one of its initiatives, not proposing a new plan. "
                "Don't submit a plan for approval. Get the work done: use your tools "
                "or dispatch sub-tasks, and if you're missing a capability, call "
                "`request_capability` and finish what you can without it."
            ),
            is_error=True,
        )
    # Idempotency: a plan may already be awaiting approval — e.g. after a restart
    # re-runs this still-``running`` task (see app.jobs.recovery). Don't create a
    # second decision; re-park on the existing one so the founder sees a single
    # plan to approve. Mirrors the chat flow's "already parked, don't double-post".
    existing = await db.scalar(
        select(DecisionRequest).where(
            DecisionRequest.task_id == task.id,
            DecisionRequest.kind == DecisionKind.plan_approval,
            DecisionRequest.status == DecisionStatus.pending,
        )
    )
    if existing is not None:
        row = await db.get(Task, task.id)
        if row is not None:
            row.status = TaskStatus.waiting_approval
        task.status = TaskStatus.waiting_approval
        await db.flush()
        return ToolOutcome(
            observation="Your plan is already awaiting the founder's approval.",
            park=True,
        )
    # Cross-task coalesce: this agent may already have a plan awaiting approval on a
    # DIFFERENT task — e.g. a new business cycle, or a fresh founder-DM task, that
    # re-derived the same plan. Stacking a second pending plan is what buried the
    # founder in duplicate "approve this plan" decisions. Don't create another; tell
    # the agent to wait on the open one. This task keeps running (no park) so it can
    # wrap up rather than deadlock on a decision it doesn't own.
    agent_pending = await db.scalar(
        select(DecisionRequest).where(
            DecisionRequest.company_id == task.company_id,
            DecisionRequest.agent_id == agent.id,
            DecisionRequest.kind == DecisionKind.plan_approval,
            DecisionRequest.status == DecisionStatus.pending,
        )
    )
    if agent_pending is not None:
        return ToolOutcome(
            observation=(
                "You already have a plan awaiting the founder's approval (from "
                "another task) — don't submit a second one. Wait for that decision "
                "to be resolved before planning again."
            ),
            is_error=True,
        )
    decision = DecisionRequest(
        company_id=task.company_id,
        agent_id=agent.id,
        task_id=task.id,
        kind=DecisionKind.plan_approval,
        summary=f"Proposed execution plan:\n\n{plan}",
        payload={"tool": "submit_plan", "plan": plan},
        status=DecisionStatus.pending,
    )
    db.add(decision)
    await db.flush()
    await chat.attach_decision_dm(db, decision=decision)
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
    decision = DecisionRequest(
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
    db.add(decision)
    await db.flush()
    await chat.attach_decision_dm(db, decision=decision)
    row = await db.get(Task, task.id)
    if row is not None:
        row.status = TaskStatus.waiting_approval
    task.status = TaskStatus.waiting_approval
    await db.flush()
    return ToolOutcome(
        observation="Over budget — escalated to the founder to authorise the extra funds.",
        park=True,
    )


async def _request_secret(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    from app.services import secrets as secrets_svc

    name = secrets_svc.normalize_name(str(args.get("name") or ""))
    reason = str(args.get("reason") or "").strip()
    allowed_host = str(args.get("allowed_host") or "").strip() or None
    if not name:
        return ToolOutcome(
            observation="A secret request needs a name (a short handle like 'stripe_api_key').",
            is_error=True,
        )
    if not reason:
        return ToolOutcome(
            observation="Tell the founder what the secret is for (the 'reason').", is_error=True
        )

    # Already have it? Then the agent can just reference the placeholder — no need to
    # bother the founder again.
    if await secrets_svc.has_secret(db, company_id=task.company_id, name=name):
        return ToolOutcome(
            observation=(
                f"The secret `{name}` is already stored. Use it by putting "
                f"{{{{secret:{name}}}}} in the relevant tool argument — it is substituted "
                "securely at the network boundary. You never see the raw value."
            )
        )

    host_line = f"\n\nIt will be bound to **{allowed_host}**." if allowed_host else ""
    decision = DecisionRequest(
        company_id=task.company_id,
        agent_id=agent.id,
        task_id=task.id,
        kind=DecisionKind.secret_request,
        summary=(
            f"**Secret requested — `{name}`**\n\n"
            f"{agent.name} needs this to proceed: {reason}{host_line}\n\n"
            "Provide it from the secure secrets panel (or reply from the app's secret "
            "form) — it is encrypted at rest and never shown to the agents. **Do not "
            "paste the value into chat.**"
        ),
        # The value is NEVER placed here — only the request metadata. Fulfilment seals
        # the value straight into the secret store (see secrets.fulfill_request).
        payload={
            "tool": "request_secret",
            "name": name,
            "reason": reason,
            "allowed_host": allowed_host,
        },
        status=DecisionStatus.pending,
    )
    db.add(decision)
    await db.flush()
    await chat.attach_decision_dm(db, decision=decision)
    row = await db.get(Task, task.id)
    if row is not None:
        row.status = TaskStatus.waiting_approval
    task.status = TaskStatus.waiting_approval
    await db.flush()
    return ToolOutcome(
        observation=(
            f"Requested the secret `{name}` from the founder. The task will resume once "
            "they provide it; then reference it as {{secret:" + name + "}}."
        ),
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
    if registrar is None:
        return unsupported_capability(
            "Registering a domain",
            hint="No real domain registrar is configured (set ABOS_DOMAIN_REGISTRAR).",
        )
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


#: Provider name under which a company's email (Resend) key is stored (BYOK).
EMAIL_KEY_PROVIDER = "resend"


async def _resolve_email_sender(db, company_id):
    """Return the email sender for this company, or ``None`` if none is wired.

    BYOK extends to email: if the founder attached a Resend key (onboarding or
    Settings), the company sends real mail via Resend — chosen for its generous
    free tier and custom-domain support — regardless of the global default, using
    the company's own ``email_from`` ("From:") address when one is set. Without a
    key, fall back to the configured sender, which is ``None`` unless the
    deployment set a global real provider (e.g. SMTP); there is no simulated
    sender, so an unconfigured environment resolves to ``None`` and the tool
    reports the capability is unsupported.
    """
    from app.integrations.email import get_email_sender
    from app.models import Company
    from app.services import apikeys

    key = await apikeys.get_plaintext_key(db, company_id=company_id, provider=EMAIL_KEY_PROVIDER)
    if key:
        from app.integrations.resend import ResendEmailSender

        # Per-company verified "From:" overrides the global ABOS_EMAIL_FROM.
        company = await db.get(Company, company_id)
        sender = company.email_from if company else None
        return ResendEmailSender(api_key=key, sender=sender or None)
    return get_email_sender()


async def _send_email(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    from app.integrations.email import EmailError
    from app.services import memory as memory_svc

    sender = await _resolve_email_sender(db, task.company_id)
    if sender is None:
        return unsupported_capability(
            "Sending email",
            hint=(
                "No email provider is connected (set ABOS_EMAIL_PROVIDER=smtp + SMTP creds, "
                "or add a Resend API key in Settings)."
            ),
        )
    try:
        res = await sender.send(to=args["to"], subject=args["subject"], body=args["body"])
    except EmailError as exc:
        return ToolOutcome(observation=f"email send failed: {exc}", is_error=True)
    # Log the outbound communication for auditability / recall.
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title=f"Email to {args['to']}: {args['subject'][:80]}",
        content=args["body"],
        source_task_id=task.id,
    )
    # Best-effort: keep a copy of the outbound email in the company's file store
    # (Communications) so there's a durable comms trail for audits/DD. Never blocks
    # the send — no-ops silently when no file provider is connected.
    from app.models.enums import FileCategory
    from app.services import files as files_svc

    await files_svc.safe_archive(
        db,
        company_id=task.company_id,
        category=FileCategory.communications,
        name=f"email-{args['to']}-{args['subject'][:60]}",
        content=f"To: {args['to']}\nSubject: {args['subject']}\n\n{args['body']}",
        source_task_id=task.id,
        description=f"Outbound email to {args['to']}",
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


async def _resolve_web_provider(db, company_id) -> tuple[object | None, object | None, str | None]:
    """Return ``(provider, funding_user_id, reason)`` for the Tavily-backed web
    tools (``web_search`` and ``web_fetch`` share one provider and one key).

    A founder can attach a Tavily key per company (onboarding, Settings, or an
    agent self-configuring it via ``configure_integration``); with one we run real,
    billable calls funded by them (``funding_user_id`` is ``None`` — their own key,
    never metered against the platform allowance).

    Without a key we fall back to the globally-configured provider. Under managed
    mode that global provider is platform-funded, so it's gated by the founder's
    managed eligibility and — when allowed — the spend is attributed to them
    (``funding_user_id`` set). When managed mode is off, the operator's global
    provider serves everyone as before. With no global provider (and no key), or
    when the founder is over their managed cap, this resolves to
    ``(None, None, reason)`` and the tool reports the capability unsupported.
    """
    from app.services import apikeys, billing

    key = await apikeys.get_plaintext_key(db, company_id=company_id, provider=WEB_SEARCH_PROVIDER)
    funding_user_id = None
    if key:
        from app.integrations.tavily import TavilyWebSearch

        provider: object | None = TavilyWebSearch(api_key=key)
    else:
        provider = get_web_search()
        if provider is not None:
            allowed, funding_user_id, reason = await billing.platform_capability_funding(
                db, company_id=company_id
            )
            if not allowed:
                return None, None, reason
    return provider, funding_user_id, None


async def _resolve_web_search(
    db, company_id
) -> tuple[object | None, int, object | None, str | None]:
    """Return ``(provider, cost_cents, funding_user_id, reason)`` for web search.

    Thin wrapper over :func:`_resolve_web_provider` that attaches the per-call
    estimated cost (basic=1 credit, advanced=2) the meter reserves up front.
    """
    provider, funding_user_id, reason = await _resolve_web_provider(db, company_id)
    if provider is None:
        return None, 0, None, reason
    multiplier = 2 if settings.tavily_search_depth == "advanced" else 1
    return provider, settings.web_search_cost_cents * multiplier, funding_user_id, None


async def _persist_search_to_memory(db, *, company_id, task, query: str, results) -> None:
    """File web-search results into shared company memory so the *fleet* keeps them.

    Search results otherwise live only in the searching agent's transcript, so a
    sibling agent (or the next cycle) can't recall them and re-runs the same query —
    the re-search loop seen in dogfooding. Persisting them as a recallable ``result``
    memory makes each search shared knowledge. Best-effort and savepoint-isolated: a
    write failure (e.g. embeddings unavailable, or the pgvector table absent in a
    reduced schema) must never fail or poison the search itself.
    """
    from app.services import memory as memory_svc

    lines = [f"- {r.title} ({r.url}): {r.snippet}" for r in results]
    content = clip("\n".join(lines), settings.web_search_max_chars)
    try:
        async with db.begin_nested():
            await memory_svc.write(
                db,
                company_id=company_id,
                type=MemoryType.result,
                title=f"Web research: {query}",
                content=content,
                source_task_id=task.id,
                # Tagged so the TTL reaper can expire stale web findings (prices,
                # stats, adoption numbers drift) without touching real work memory.
                structured={"source": "web_search"},
            )
    except Exception:
        pass


async def _web_search(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    query = args["query"]
    search, cost_cents, funding_user_id, reason = await _resolve_web_search(db, task.company_id)
    if search is None:
        if settings.web_search_founder_fallback:
            # Human-backed search: ask the founder (or their AI operator) to run it and
            # reply with the findings — the task parks on the DM until they answer.
            from app.runtime.tools.chat import escalate_to_founder

            return await escalate_to_founder(
                db,
                ctx,
                agent=agent,
                task=task,
                summary=(
                    f"**WEB SEARCH:** {query}\n\n"
                    "No automated web-search provider is connected, so this comes to you: "
                    "please run this search and reply with the findings (titles, links, and "
                    "the key facts). Your reply is delivered straight back to the agent."
                ),
            )
        return unsupported_capability(
            "Web search",
            hint=reason
            or "No web-search provider is connected — self-configure one with "
            "`configure_integration` (provider 'tavily'), or add a Tavily key in Settings.",
        )
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
                    credits * settings.web_search_cost_cents if credits is not None else cost_cents
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
                funding_user_id=funding_user_id,
                funding_kind="web_search",
            )
            results = captured.get("results", [])
        else:
            results = await search.search(query, max_results=settings.web_search_max_results)
    except WebSearchError as exc:
        return ToolOutcome(observation=f"web search failed: {exc}", is_error=True)
    if not results:
        return ToolOutcome(observation=f"no web results for {query!r}")
    # Share the findings with the whole fleet (recallable memory), not just this
    # agent's transcript — so nobody re-runs the same search.
    await _persist_search_to_memory(
        db, company_id=task.company_id, task=task, query=query, results=results
    )
    lines = [f"- {r.title} ({r.url})\n  {r.snippet}" for r in results]
    observation = f"Web results for {query!r}:\n" + "\n".join(lines)
    return ToolOutcome(observation=clip(observation, settings.web_search_max_chars))


def _normalize_urls(args: dict) -> list[str]:
    """The URLs a web_fetch call asked for: accept a single ``url`` or a ``urls``
    list, de-duplicated and order-preserving, capped at ``web_fetch_max_urls``."""
    raw = args.get("urls")
    if raw is None:
        one = args.get("url")
        raw = [one] if one else []
    if isinstance(raw, str):
        raw = [raw]
    seen: set[str] = set()
    urls: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        u = str(item or "").strip()
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    return urls[: settings.web_fetch_max_urls]


async def _web_fetch(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    urls = _normalize_urls(args)
    if not urls:
        return ToolOutcome(
            observation="Provide a `url` (or a `urls` list) of page(s) to fetch.",
            is_error=True,
        )
    provider, cost_cents, funding_user_id, reason = await _resolve_web_search(db, task.company_id)
    # web_fetch shares the Tavily provider/key with web_search; a resolved provider
    # that can't extract (e.g. a search-only test double or future provider) reports
    # the capability unsupported rather than pretending to read the pages.
    if provider is None and settings.web_search_founder_fallback:
        # Human-backed fetch: ask the founder (or their AI) to open the URL(s) and
        # report the content — the task parks on the DM until they reply.
        from app.runtime.tools.chat import escalate_to_founder

        url_lines = "\n".join(f"- {u}" for u in urls)
        return await escalate_to_founder(
            db,
            ctx,
            agent=agent,
            task=task,
            summary=(
                f"**WEB FETCH** — please open these page(s) and reply with the key content:\n\n"
                f"{url_lines}\n\n"
                "No automated fetch provider is connected, so this comes to you; your reply "
                "is delivered straight back to the agent."
            ),
        )
    if provider is None or not hasattr(provider, "extract"):
        return unsupported_capability(
            "Fetching web pages",
            hint=reason
            or "No web-fetch provider is connected — self-configure one with "
            "`configure_integration` (provider 'tavily'), or add a Tavily key in Settings.",
        )
    # Estimate: ~1 credit per 5 URLs (×2 at advanced depth). The meter reserves this
    # up front, then reconciles to Tavily's reported credits — same path as search.
    import math

    depth_mult = 2 if settings.tavily_extract_depth == "advanced" else 1
    estimate_cents = math.ceil(len(urls) / 5) * settings.web_search_cost_cents * depth_mult
    try:
        if cost_cents > 0:
            captured: dict = {}

            async def _do() -> tuple[int, str | None, dict | None]:
                fetched = await provider.extract(urls)
                captured["results"] = fetched
                credits = getattr(provider, "last_usage_credits", None)
                actual_cents = (
                    credits * settings.web_search_cost_cents
                    if credits is not None
                    else estimate_cents
                )
                request_id = getattr(provider, "last_request_id", None)
                return (
                    actual_cents,
                    request_id,
                    {"urls": len(urls), "credits": credits},
                )

            await ctx.cost_meter.metered_external(
                company_id=task.company_id,
                agent_id=agent.id,
                task_id=task.id,
                estimated_cents=estimate_cents,
                vendor=f"web_fetch({settings.web_search_provider})",
                sku=urls[0][:120],
                action=_do,
                description=f"web fetch: {len(urls)} url(s)",
                funding_user_id=funding_user_id,
                funding_kind="web_search",
            )
            results = captured.get("results", [])
        else:
            results = await provider.extract(urls)
    except WebSearchError as exc:
        return ToolOutcome(observation=f"web fetch failed: {exc}", is_error=True)
    ok = [r for r in results if not r.error and r.content]
    failed = [r for r in results if r.error or not r.content]
    if not ok:
        detail = "; ".join(f"{r.url}: {r.error or 'no content'}" for r in failed) or "no content"
        return ToolOutcome(observation=f"could not fetch any of the URLs ({detail})", is_error=True)
    blocks = [f"## {r.url}\n{r.content}" for r in ok]
    observation = "Fetched page content:\n\n" + "\n\n".join(blocks)
    if failed:
        observation += "\n\nCould not fetch: " + ", ".join(r.url for r in failed)
    return ToolOutcome(observation=clip(observation, settings.web_fetch_max_chars))


#: Sub-task statuses that mean the child is still working (not yet collectible).
_IN_FLIGHT = (
    TaskStatus.queued,
    TaskStatus.running,
    TaskStatus.waiting_approval,
    TaskStatus.auditing,
)


async def _collect_results(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    rows = (
        await db.scalars(
            select(Task).where(Task.parent_task_id == task.id).order_by(Task.created_at.asc())
        )
    ).all()
    if not rows:
        return ToolOutcome(observation="You have not dispatched any sub-tasks.")
    done = [c for c in rows if c.status is TaskStatus.done]
    pending = [c for c in rows if c.status in _IN_FLIGHT]
    failed = [c for c in rows if c.status in (TaskStatus.failed, TaskStatus.blocked)]
    incomplete = [c for c in rows if c.status is TaskStatus.needs_continuation]
    lines: list[str] = []
    if done:
        lines.append("Completed sub-task results:")
        for child in done:
            summary = (child.output or {}).get("summary", "") if child.output else ""
            clipped = clip(summary, settings.collect_results_summary_chars)
            lines.append(f"- {child.goal[:80]}: {clipped or '(no summary)'}")
    if failed:
        lines.append(
            f"Failed/blocked sub-tasks ({len(failed)}): " + ", ".join(c.goal[:50] for c in failed)
        )
    if incomplete:
        lines.append(f"Ran out of steps before finishing ({len(incomplete)}):")
        for child in incomplete:
            summary = (child.output or {}).get("summary", "") if child.output else ""
            clipped = clip(summary, settings.collect_results_summary_chars)
            lines.append(f"- {child.goal[:80]}: {clipped or '(no partial summary)'}")
    if pending:
        # Tell the parent to wait rather than synthesize half the picture.
        lines.append(
            f"Still running ({len(pending)}): "
            + ", ".join(c.goal[:50] for c in pending)
            + ". Check back before synthesizing — these have not reported yet."
        )
    return ToolOutcome(observation=clip("\n".join(lines), settings.collect_results_total_chars))


async def _request_decision(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    """Escalate an open-ended decision to the founder as a DM that waits for a reply.

    Consolidated into chat: rather than a separate decision-inbox row, the question
    becomes a message in the agent↔founder thread and the task parks until the
    founder replies (the reply is delivered back to the agent on resume).
    """
    from app.runtime.tools.chat import escalate_to_founder

    summary = str(args.get("summary") or "").strip()
    if not summary:
        return ToolOutcome(
            observation="Describe what you need the founder to decide.", is_error=True
        )
    return await escalate_to_founder(db, ctx, agent=agent, task=task, summary=summary)


async def _request_user_action(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    from app.runtime.tools.chat import escalate_to_founder

    action = str(args.get("action") or "").strip()
    if not action:
        return ToolOutcome(
            observation="Describe the action you need the founder to perform.", is_error=True
        )
    reason = str(args.get("reason") or "").strip()
    # A credential must never be solicited through this tool: the founder's reply lands
    # as a plaintext chat message (no sealing, no redaction) and flows back into the
    # agent's transcript. Redirect any credential-shaped ask to `request_secret`, whose
    # value is envelope-encrypted, never returned, and spliced in only at the outbound
    # boundary. Mirrors how `_request_secret` short-circuits when a secret already exists.
    haystack = f"{action}\n{reason}".lower()
    if any(
        kw in haystack
        for kw in (
            "api key",
            "api token",
            "access key",
            "secret key",
            "private key",
            "client secret",
            "password",
            "passphrase",
            "token",
            "secret",
            "credential",
        )
    ):
        return ToolOutcome(
            observation=(
                "This looks like a request for a credential (API key, token, password, …). "
                "Do NOT ask for secrets here — a chat reply would expose the value in "
                "plaintext. Use the `request_secret` tool instead: it stores the value "
                "encrypted, never shows it to you, and you reference it as {{secret:name}}."
            ),
            is_error=True,
        )
    summary = (
        "**Action requested**\n\n"
        f"The {agent.role.value} agent needs you to do something it can't do itself:\n\n"
        f"{action}"
    )
    if reason:
        summary += f"\n\n_Why:_ {reason}"
    summary += "\n\nDo this, then **reply here with the result** so the agent can continue with it."
    return await escalate_to_founder(db, ctx, agent=agent, task=task, summary=summary)


async def _post_mission_update(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    from app.services import mission_log

    headline = str(args.get("headline") or "").strip()
    if not headline:
        return ToolOutcome(
            observation="A mission update needs a short headline describing the milestone.",
            is_error=True,
        )
    detail = str(args.get("detail") or "").strip() or None
    entry = await mission_log.record(
        task.company_id,
        agent_id=agent.id,
        agent_name=agent.name,
        role=agent.role.value,
        headline=headline,
        detail=detail,
        kind="update",
    )
    if entry is None:
        # The live log is a best-effort convenience, not a source of truth — if it
        # couldn't be posted, say so plainly rather than pretend it landed.
        return ToolOutcome(
            observation="Mission update could not be posted right now; carry on with your work."
        )
    return ToolOutcome(observation=f"posted mission update: {entry['headline']}")


async def _report_result(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return ToolOutcome(observation="reported", stop=True)


HANDLERS = {
    "dispatch_task": _dispatch_task,
    "dispatch_tasks": _dispatch_tasks,
    "submit_plan": _submit_plan,
    "request_budget": _request_budget,
    "request_secret": _request_secret,
    "write_memory": _write_memory,
    "register_domain": _register_domain,
    "send_email": _send_email,
    "request_decision": _request_decision,
    "request_user_action": _request_user_action,
    "post_mission_update": _post_mission_update,
    "report_result": _report_result,
    "read_metrics": _read_metrics,
    "record_metric": _record_metric,
    "web_search": _web_search,
    "web_fetch": _web_fetch,
    "collect_results": _collect_results,
}
