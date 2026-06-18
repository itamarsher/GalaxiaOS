"""Sales tools: lead logging, deal-stage tracking, and follow-up scheduling.

These tools are NOT connected to a real CRM, calendar, or any external system, so
they are unsupported in this environment. They used to be "simulated": they wrote a
lead/deal/follow-up into Company Memory and bumped a metric signal, then returned a
fabricated success. That fabrication is exactly what produced hallucinated plans —
phantom leads and revenue surfaced back into the planning prompts as if they were
real. Each handler now reports the capability is unavailable and points the agent at
``request_capability`` instead of inventing pipeline that does not exist.
"""

from __future__ import annotations

from app.models import Agent, Task
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome, unsupported_capability

#: Allowed deal stages, in pipeline order (kept for the ``update_deal`` schema).
DEAL_STAGES: tuple[str, ...] = ("new", "qualified", "proposal", "won", "lost")


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
        description="Schedule a follow-up touchpoint with a lead.",
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
    return unsupported_capability(
        "Logging a sales lead",
        hint="There is no CRM connected, so the lead would only be invented, not stored.",
    )


async def _update_deal(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return unsupported_capability(
        "Updating a deal stage",
        hint="There is no CRM connected; record real, measured revenue with record_metric.",
    )


async def _schedule_followup(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return unsupported_capability(
        "Scheduling a follow-up",
        hint="There is no CRM or calendar connected to hold the reminder.",
    )


HANDLERS = {
    "log_lead": _log_lead,
    "update_deal": _update_deal,
    "schedule_followup": _schedule_followup,
}
