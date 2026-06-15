"""Sales tools: lead logging, deal-stage tracking, and follow-up scheduling.

Area-specific tools for the sales function. Everything here is deterministic and
simulated — leads/deals/follow-ups are persisted only as institutional memory and
metric signals; no CRM, calendar, or network calls. Outreach email is handled by
the core ``send_email`` tool and is intentionally not re-implemented here.
"""

from __future__ import annotations

from app.models import Agent, Task
from app.models.enums import MemoryType, MetricSource
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome
from app.services import memory as memory_svc
from app.services import metrics as metrics_svc

#: Allowed deal stages, in pipeline order.
DEAL_STAGES: tuple[str, ...] = ("new", "qualified", "proposal", "won", "lost")


def validate_stage(stage: str) -> str:
    """Return a normalized deal stage or raise ``ValueError`` if unknown."""
    normalized = str(stage).strip().lower()
    if normalized not in DEAL_STAGES:
        raise ValueError(
            f"invalid stage {stage!r}; expected one of {', '.join(DEAL_STAGES)}"
        )
    return normalized


def format_lead_summary(args: dict) -> str:
    """Build a human-readable, deterministic summary line for a logged lead."""
    parts = [f"name={args['name']}"]
    for field in ("email", "company", "source"):
        value = args.get(field)
        if value:
            parts.append(f"{field}={value}")
    note = args.get("note")
    if note:
        parts.append(f"note={note}")
    return " | ".join(parts)


def format_deal_summary(lead: str, stage: str, amount_cents: int | None) -> str:
    """Build a deterministic summary line for a deal-stage change."""
    line = f"lead={lead} -> stage={stage}"
    if amount_cents is not None:
        line += f" (${amount_cents / 100:.2f})"
    return line


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="log_lead",
        description="Record a new sales lead (name, optional email/company/source/note).",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Lead's full name."},
                "email": {"type": "string"},
                "company": {"type": "string"},
                "source": {"type": "string", "description": "Where the lead came from."},
                "note": {"type": "string"},
            },
            "required": ["name"],
        },
    ),
    ToolSpec(
        name="update_deal",
        description=(
            "Move a deal to a new pipeline stage "
            "(new|qualified|proposal|won|lost); records revenue when won."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "lead": {"type": "string", "description": "Lead or deal identifier."},
                "stage": {
                    "type": "string",
                    "enum": list(DEAL_STAGES),
                },
                "amount_cents": {
                    "type": "integer",
                    "description": "Deal value in cents (recorded as revenue when won).",
                },
                "note": {"type": "string"},
            },
            "required": ["lead", "stage"],
        },
    ),
    ToolSpec(
        name="schedule_followup",
        description="Schedule a follow-up touchpoint with a lead (deterministic; no real calendar).",
        input_schema={
            "type": "object",
            "properties": {
                "lead": {"type": "string", "description": "Lead or deal identifier."},
                "when": {"type": "string", "description": "When to follow up (free text)."},
                "note": {"type": "string"},
            },
            "required": ["lead", "when"],
        },
    ),
]


async def _log_lead(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    name = args["name"]
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title=f"Lead: {name}",
        content=format_lead_summary(args),
        source_task_id=task.id,
    )
    await metrics_svc.record_signal(
        db,
        company_id=task.company_id,
        name="leads_logged",
        value=1,
        source=MetricSource.agent,
        note=f"lead: {name}",
    )
    return ToolOutcome(observation=f"logged lead {name}")


async def _update_deal(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    lead = args["lead"]
    try:
        stage = validate_stage(args["stage"])
    except ValueError as exc:
        return ToolOutcome(observation=str(exc), is_error=True)
    amount_cents = args.get("amount_cents")
    summary = format_deal_summary(lead, stage, amount_cents)
    note = args.get("note")
    content = f"{summary}\n{note}" if note else summary
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.decision,
        title=f"Deal: {lead} -> {stage}",
        content=content,
        source_task_id=task.id,
    )
    if stage == "won" and amount_cents is not None:
        await metrics_svc.record_signal(
            db,
            company_id=task.company_id,
            name="revenue",
            value=int(amount_cents) / 100,
            unit="USD",
            source=MetricSource.agent,
            note=f"deal won: {lead}",
        )
    return ToolOutcome(observation=f"updated deal {summary}")


async def _schedule_followup(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    lead = args["lead"]
    when = args["when"]
    note = args.get("note")
    content = f"Follow up with {lead} at {when}."
    if note:
        content += f" Note: {note}"
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.decision,
        title=f"Follow-up: {lead} @ {when}",
        content=content,
        source_task_id=task.id,
    )
    return ToolOutcome(observation=f"scheduled follow-up with {lead} at {when}")


HANDLERS = {
    "log_lead": _log_lead,
    "update_deal": _update_deal,
    "schedule_followup": _schedule_followup,
}
