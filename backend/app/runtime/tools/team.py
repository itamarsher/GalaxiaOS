"""CEO org-management tools: team, budget, and operating directives.

These let the CEO agent shape its own team within the founder's monthly budget and
keep the whole fleet aligned to emerging directives. The company budget is a hard
ceiling; each agent's ``monthly_budget_cents`` is a soft cap reserving a slice of
it. The *unallocated pool* — the headroom not yet earmarked by an active agent — is
what the CEO can hand to a new hire (see
:func:`app.services.budget.allocation_overview`).

- ``hire_agent`` adds a native functional agent reporting to the CEO, drawing
  its allocation from the pool. If the pool can't cover it, the CEO is told to
  free budget (``set_agent_budget``) or pause an agent first.
- ``pause_agent`` parks an agent; its unspent allocation flows back to the pool.
- ``resume_agent`` re-activates one, re-claiming its allocation from the pool.
- ``set_agent_budget`` reallocates an existing agent's monthly cap.
- ``list_team`` shows the roster and the live budget picture.
- ``get_company_playbook`` / ``update_company_playbook`` read and edit the global
  operating playbook injected into every agent's launch prompt — the CEO's lever
  for rolling out emerging directives to the whole fleet at once.
- ``set_agent_directive`` updates one agent's company-specific directive (its
  ``system_prompt``), so the CEO can retune an individual agent as needed.

All are CEO-only (guarded at the top of each handler), matching the "CEO only"
convention used by ``submit_plan``.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Agent, AgentEdge, Company, DecisionRequest, Task
from app.models.enums import (
    AgentBackendType,
    AgentRole,
    AgentSource,
    AgentStatus,
    AutonomyLevel,
    DecisionKind,
    DecisionStatus,
    EdgeRelation,
    TaskStatus,
)
from app.providers.base import ToolSpec
from app.runtime.prompts import effective_playbook
from app.runtime.tools.base import ToolOutcome, consume_approval_grant
from app.services import budget as budget_svc

#: Cap on the global playbook so a runaway edit can't bloat every agent's prompt.
_MAX_PLAYBOOK_CHARS = 8000
#: Cap on a single agent's directive.
_MAX_DIRECTIVE_CHARS = 4000

# Roles the CEO may hire into (the CEO can't hire another CEO).
_HIREABLE_ROLES = [r.value for r in AgentRole if r is not AgentRole.ceo]

SPECS: list[ToolSpec] = [
    ToolSpec(
        name="list_team",
        description=(
            "CEO only. List the current agent roster (role, name, status, and "
            "monthly budget allocation vs. spend) together with the company's "
            "budget and the unallocated pool you can hand to a new hire. Call this "
            "before hiring, pausing, or reallocating so you decide from real numbers."
        ),
        input_schema={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name="hire_agent",
        description=(
            "CEO only. Propose hiring an additional functional agent that reports to "
            "you, allocating it a monthly budget drawn from the unallocated pool. This "
            "REQUESTS the founder's permission and pauses until they approve — it does "
            "not hire on its own — so they can weigh in on growing the team. Use it only "
            "when the existing team is genuinely the bottleneck, and keep the proposed "
            "budget modest (don't drain the reserve). If the pool can't cover the "
            "allocation you'll be told to free budget first (lower another agent's "
            "allocation with set_agent_budget, or pause an agent)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "enum": _HIREABLE_ROLES,
                    "description": "The functional role for the new agent.",
                },
                "name": {"type": "string", "description": "A short name for the agent."},
                "responsibility": {
                    "type": "string",
                    "description": "What this agent owns (becomes its system prompt).",
                },
                "monthly_budget_cents": {
                    "type": "integer",
                    "description": "Monthly budget to allocate this agent, in cents.",
                },
            },
            "required": ["role", "name", "monthly_budget_cents"],
        },
    ),
    ToolSpec(
        name="pause_agent",
        description=(
            "CEO only. Pause an agent (by name, or by role if unambiguous). A "
            "paused agent runs no tasks and its unspent budget allocation returns "
            "to the pool, freeing it for a new hire or another agent."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The agent's name."},
                "role": {"type": "string", "description": "The agent's role (if name omitted)."},
            },
        },
    ),
    ToolSpec(
        name="resume_agent",
        description=(
            "CEO only. Resume a paused agent (by name, or by role if unambiguous), "
            "re-claiming its budget allocation from the pool. If the pool can't "
            "cover it you'll be told to free budget first."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The agent's name."},
                "role": {"type": "string", "description": "The agent's role (if name omitted)."},
            },
        },
    ),
    ToolSpec(
        name="set_agent_budget",
        description=(
            "CEO only. Reallocate an existing agent's monthly budget cap (by name, "
            "or by role if unambiguous). Lowering a cap returns budget to the pool; "
            "raising it draws from the pool. Use this to reallocate existing team "
            "budget before hiring when the pool is empty."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The agent's name."},
                "role": {"type": "string", "description": "The agent's role (if name omitted)."},
                "monthly_budget_cents": {
                    "type": "integer",
                    "description": "The agent's new monthly budget cap, in cents.",
                },
            },
            "required": ["monthly_budget_cents"],
        },
    ),
    ToolSpec(
        name="get_company_playbook",
        description=(
            "CEO only. Read the company's current operating playbook — the global "
            "system prompt every agent is initialized with. Call this before editing "
            "it so you amend the live directives rather than overwriting from memory."
        ),
        input_schema={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name="update_company_playbook",
        description=(
            "CEO only. Replace the company's operating playbook — the global system "
            "prompt injected into EVERY agent's launch prompt. Use this to roll out an "
            "emerging directive to the whole fleet (it takes effect on each agent's next "
            "task). Pass the FULL new playbook text (read it first with "
            "get_company_playbook and edit), not just the delta."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "playbook": {
                    "type": "string",
                    "description": "The complete new operating playbook (Markdown/plain text).",
                },
            },
            "required": ["playbook"],
        },
    ),
    ToolSpec(
        name="set_agent_directive",
        description=(
            "CEO only. Set one agent's company-specific directive — the part of its "
            "launch prompt describing what it owns and how it should operate (by name, "
            "or by role if unambiguous). Use this to retune a single agent as its remit "
            "changes; it takes effect on that agent's next task. For directives that "
            "apply to everyone, edit the playbook instead."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The agent's name."},
                "role": {"type": "string", "description": "The agent's role (if name omitted)."},
                "directive": {
                    "type": "string",
                    "description": "The agent's new directive (what it owns and how it operates).",
                },
            },
            "required": ["directive"],
        },
    ),
]


def _usd(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _require_ceo(agent: Agent) -> ToolOutcome | None:
    """Team management is the CEO's lever; everyone else gets a clear refusal."""
    if agent.role is not AgentRole.ceo:
        return ToolOutcome(
            observation="Only the CEO can manage the team (hire/pause/resume/reallocate).",
            is_error=True,
        )
    return None


async def _resolve_target(
    db, *, company_id, args: dict, exclude_id=None
) -> tuple[Agent | None, str | None]:
    """Find the agent named in ``args`` (by ``name``, else by ``role``).

    Returns ``(agent, error)``: exactly one is non-None. Name match wins and is
    case-insensitive; a role that matches several agents is reported as
    ambiguous so the CEO disambiguates by name.
    """
    name = str(args.get("name") or "").strip()
    role = str(args.get("role") or "").strip()
    if not name and not role:
        return None, "Specify which agent by `name` (or `role`)."

    stmt = select(Agent).where(Agent.company_id == company_id)
    if exclude_id is not None:
        stmt = stmt.where(Agent.id != exclude_id)
    candidates = (await db.scalars(stmt)).all()

    if name:
        matches = [a for a in candidates if a.name.lower() == name.lower()]
        if not matches:
            return None, f"No agent named {name!r}."
        if len(matches) > 1:
            return None, f"Several agents are named {name!r}; that's ambiguous."
        return matches[0], None

    try:
        role_enum = AgentRole(role)
    except ValueError:
        return None, f"Unknown role {role!r}."
    matches = [a for a in candidates if a.role is role_enum]
    if not matches:
        return None, f"No {role} agent."
    if len(matches) > 1:
        names = ", ".join(a.name for a in matches)
        return None, f"Several {role} agents ({names}); name the one you mean."
    return matches[0], None


async def _list_team(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if (refusal := _require_ceo(agent)) is not None:
        return refusal
    overview = await budget_svc.allocation_overview(db, task.company_id)
    agents = (
        await db.scalars(
            select(Agent).where(Agent.company_id == task.company_id).order_by(Agent.created_at)
        )
    ).all()
    lines = []
    for a in agents:
        used = await budget_svc.agent_spent(db, a.id)
        if a.monthly_budget_cents is None:
            alloc = "uncapped"
        else:
            alloc = f"{_usd(used)}/{_usd(a.monthly_budget_cents)}"
        lines.append(f"- {a.name} ({a.role.value}, {a.status.value}): spend {alloc}")
    roster = "\n".join(lines) or "(no agents)"
    if overview is None:
        return ToolOutcome(observation=f"Team:\n{roster}\n\nNo budget configured.")
    budget_line = (
        f"Budget: limit {_usd(overview['limit_cents'])}, "
        f"spent {_usd(overview['spent_cents'])}, reserved {_usd(overview['reserved_cents'])}, "
        f"earmarked {_usd(overview['earmarked_cents'])}. "
        f"Unallocated pool: {_usd(overview['pool_cents'])}."
    )
    return ToolOutcome(observation=f"Team:\n{roster}\n\n{budget_line}")


def _reallocate_hint(pool_cents: int) -> str:
    return (
        f"Only {_usd(max(0, pool_cents))} is unallocated. Free budget first: lower "
        "another agent's allocation with `set_agent_budget`, or `pause_agent` to "
        "return its unspent budget to the pool — then try again."
    )


async def _hire_agent(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if (refusal := _require_ceo(agent)) is not None:
        return refusal

    try:
        role = AgentRole(str(args["role"]))
    except ValueError:
        role = AgentRole.custom
    if role is AgentRole.ceo:
        return ToolOutcome(observation="There can only be one CEO.", is_error=True)
    name = str(args["name"]).strip()
    if not name:
        return ToolOutcome(observation="A new agent needs a name.", is_error=True)
    allocation = int(args["monthly_budget_cents"])
    if allocation <= 0:
        return ToolOutcome(
            observation="Allocate the new agent a positive monthly budget.", is_error=True
        )

    overview = await budget_svc.allocation_overview(db, task.company_id)
    if overview is None:
        return ToolOutcome(observation="No budget configured; can't hire.", is_error=True)
    pool = overview["pool_cents"]
    if allocation > pool:
        return ToolOutcome(
            observation=(
                f"Can't hire {name}: it needs {_usd(allocation)}/mo but "
                + _reallocate_hint(pool)
            ),
            is_error=True,
        )

    # Growing the team is the founder's call: rather than hire outright, ask for
    # permission so they can weigh in on the hiring process. On resume after they
    # approve, a one-shot grant lets the same hire go through instead of asking
    # again forever (mirrors submit_plan / request_budget).
    responsibility = str(args.get("responsibility") or "").strip()
    if not await consume_approval_grant(db, task_id=task.id, tool="hire_agent"):
        db.add(
            DecisionRequest(
                company_id=task.company_id,
                agent_id=agent.id,
                task_id=task.id,
                kind=DecisionKind.hire_approval,
                summary=(
                    f"**Hire request — approval needed**\n\n"
                    f"Proposing to hire **{name}** ({role.value}) at "
                    f"**{_usd(allocation)}/mo**, drawn from the unallocated pool "
                    f"({_usd(pool)} available).\n\n"
                    f"Responsibility: {responsibility or '(none given)'}\n\n"
                    "Approve to add them to the team (note any changes to role or budget), "
                    "or reject to keep the current team."
                ),
                payload={"tool": "hire_agent", "args": args},
                status=DecisionStatus.pending,
            )
        )
        row = await db.get(Task, task.id)
        if row is not None:
            row.status = TaskStatus.waiting_approval
        task.status = TaskStatus.waiting_approval  # keep the in-memory copy consistent
        await db.flush()
        return ToolOutcome(
            observation=(
                f"Requested the founder's approval to hire {name} ({role.value}) at "
                f"{_usd(allocation)}/mo. Hiring is paused until they respond."
            ),
            park=True,
        )

    new_agent = Agent(
        company_id=task.company_id,
        role=role,
        name=name,
        system_prompt=responsibility,
        autonomy_level=AutonomyLevel.approve_required,
        monthly_budget_cents=allocation,
        source=AgentSource.hired,
        backend_type=AgentBackendType.native,
        reports_to_agent_id=agent.id,
    )
    db.add(new_agent)
    await db.flush()
    db.add(
        AgentEdge(
            company_id=task.company_id,
            from_agent_id=new_agent.id,
            to_agent_id=agent.id,
            relation=EdgeRelation.reports_to,
        )
    )
    await db.flush()
    return ToolOutcome(
        observation=(
            f"Hired {name} ({role.value}) at {_usd(allocation)}/mo, reporting to you. "
            f"Unallocated pool now {_usd(pool - allocation)}."
        )
    )


async def _pause_agent(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if (refusal := _require_ceo(agent)) is not None:
        return refusal
    target, error = await _resolve_target(
        db, company_id=task.company_id, args=args, exclude_id=agent.id
    )
    if error is not None:
        return ToolOutcome(observation=error, is_error=True)
    if target.role is AgentRole.ceo:
        return ToolOutcome(observation="The CEO can't be paused.", is_error=True)
    if target.status is AgentStatus.paused:
        return ToolOutcome(observation=f"{target.name} is already paused.")

    used = await budget_svc.agent_spent(db, target.id)
    freed = (
        max(0, target.monthly_budget_cents - used)
        if target.monthly_budget_cents is not None
        else 0
    )
    target.status = AgentStatus.paused
    await db.flush()
    overview = await budget_svc.allocation_overview(db, task.company_id)
    pool_note = f" Pool now {_usd(overview['pool_cents'])}." if overview else ""
    return ToolOutcome(
        observation=(
            f"Paused {target.name}. Returned {_usd(freed)} of unspent budget to the pool."
            + pool_note
        )
    )


async def _resume_agent(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if (refusal := _require_ceo(agent)) is not None:
        return refusal
    target, error = await _resolve_target(
        db, company_id=task.company_id, args=args, exclude_id=agent.id
    )
    if error is not None:
        return ToolOutcome(observation=error, is_error=True)
    if target.status is AgentStatus.active:
        return ToolOutcome(observation=f"{target.name} is already active.")

    # The target is paused, so the pool excludes it; re-claiming its unspent
    # allocation must fit the pool as it stands now.
    overview = await budget_svc.allocation_overview(db, task.company_id)
    if target.monthly_budget_cents is not None and overview is not None:
        used = await budget_svc.agent_spent(db, target.id)
        needed = max(0, target.monthly_budget_cents - used)
        if needed > overview["pool_cents"]:
            return ToolOutcome(
                observation=(
                    f"Can't resume {target.name}: re-claiming its {_usd(needed)} allocation "
                    "doesn't fit. " + _reallocate_hint(overview["pool_cents"])
                ),
                is_error=True,
            )
    target.status = AgentStatus.active
    await db.flush()
    after = await budget_svc.allocation_overview(db, task.company_id)
    pool_note = f" Pool now {_usd(after['pool_cents'])}." if after else ""
    return ToolOutcome(observation=f"Resumed {target.name}.{pool_note}")


async def _set_agent_budget(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if (refusal := _require_ceo(agent)) is not None:
        return refusal
    new_cap = int(args["monthly_budget_cents"])
    if new_cap < 0:
        return ToolOutcome(observation="A budget cap can't be negative.", is_error=True)
    target, error = await _resolve_target(db, company_id=task.company_id, args=args)
    if error is not None:
        return ToolOutcome(observation=error, is_error=True)

    used = await budget_svc.agent_spent(db, target.id)
    if new_cap < used:
        return ToolOutcome(
            observation=(
                f"{target.name} has already spent {_usd(used)}; its cap can't be set below that."
            ),
            is_error=True,
        )

    overview = await budget_svc.allocation_overview(db, task.company_id)
    old_cap = target.monthly_budget_cents
    # Only an active agent's allocation draws on the pool; a raise must fit.
    if target.status is AgentStatus.active and overview is not None:
        old_unspent = max(0, old_cap - used) if old_cap is not None else 0
        new_unspent = max(0, new_cap - used)
        extra = new_unspent - old_unspent
        if extra > overview["pool_cents"]:
            return ToolOutcome(
                observation=(
                    f"Can't raise {target.name}'s budget by that much. "
                    + _reallocate_hint(overview["pool_cents"])
                ),
                is_error=True,
            )
    target.monthly_budget_cents = new_cap
    await db.flush()
    after = await budget_svc.allocation_overview(db, task.company_id)
    pool_note = f" Pool now {_usd(after['pool_cents'])}." if after else ""
    old_str = _usd(old_cap) if old_cap is not None else "uncapped"
    return ToolOutcome(
        observation=f"Set {target.name}'s budget to {_usd(new_cap)}/mo (was {old_str}).{pool_note}"
    )


async def _get_company_playbook(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if (refusal := _require_ceo(agent)) is not None:
        return refusal
    company = await db.get(Company, task.company_id)
    raw = company.playbook if company else None
    text = effective_playbook(raw)
    origin = "customized" if (raw or "").strip() else "platform default (not yet customized)"
    return ToolOutcome(observation=f"Company operating playbook ({origin}):\n\n{text}")


async def _update_company_playbook(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if (refusal := _require_ceo(agent)) is not None:
        return refusal
    playbook = str(args.get("playbook") or "").strip()
    if not playbook:
        return ToolOutcome(
            observation="The playbook can't be empty. Pass the full new directives text.",
            is_error=True,
        )
    if len(playbook) > _MAX_PLAYBOOK_CHARS:
        return ToolOutcome(
            observation=(
                f"That playbook is too long ({len(playbook)} chars; max {_MAX_PLAYBOOK_CHARS}). "
                "Keep it to the directives that matter — it's prepended to every agent's prompt."
            ),
            is_error=True,
        )
    company = await db.get(Company, task.company_id)
    if company is None:
        return ToolOutcome(observation="Company not found.", is_error=True)
    company.playbook = playbook
    await db.flush()
    return ToolOutcome(
        observation=(
            "Updated the company operating playbook. Every agent picks up the new "
            "directives on its next task."
        )
    )


async def _set_agent_directive(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if (refusal := _require_ceo(agent)) is not None:
        return refusal
    directive = str(args.get("directive") or "").strip()
    if not directive:
        return ToolOutcome(
            observation="A directive can't be empty. Describe what the agent owns.",
            is_error=True,
        )
    if len(directive) > _MAX_DIRECTIVE_CHARS:
        return ToolOutcome(
            observation=f"That directive is too long (max {_MAX_DIRECTIVE_CHARS} chars).",
            is_error=True,
        )
    target, error = await _resolve_target(db, company_id=task.company_id, args=args)
    if error is not None:
        return ToolOutcome(observation=error, is_error=True)
    target.system_prompt = directive
    await db.flush()
    return ToolOutcome(
        observation=f"Updated {target.name}'s directive. It applies on {target.name}'s next task."
    )


HANDLERS = {
    "list_team": _list_team,
    "hire_agent": _hire_agent,
    "pause_agent": _pause_agent,
    "resume_agent": _resume_agent,
    "set_agent_budget": _set_agent_budget,
    "get_company_playbook": _get_company_playbook,
    "update_company_playbook": _update_company_playbook,
    "set_agent_directive": _set_agent_directive,
}
