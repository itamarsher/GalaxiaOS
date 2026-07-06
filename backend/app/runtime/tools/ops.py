"""Operations (OPS) tools: notifications, calendar events, and ops logging.

``send_notification`` (slack/sms/webhook) and ``create_calendar_event`` reach
systems OUTSIDE the company and there is no real provider wired for them, so they
are unsupported here — they previously fabricated a delivered notification / booked
event, which is the kind of fake success that misleads planning. They now report the
capability is unavailable and point the agent at ``request_capability``.

``log_ops_event`` is different: it records an operational event to the company's own
memory for auditability and recall. That is a genuine internal write — no external
side effect to fake — so it stays.
"""

from __future__ import annotations

from app.models import Agent, Task
from app.models.enums import MemoryType
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome, unsupported_capability
from app.services import memory as memory_svc

_NOTIFY_CHANNELS = ("slack", "sms", "webhook")
_OPS_SEVERITIES = ("info", "warning", "incident")


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="send_notification",
        description=(
            "Send a non-email notification (Slack message, SMS, or webhook). "
            "For email use the send_email tool."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "enum": list(_NOTIFY_CHANNELS)},
                "target": {
                    "type": "string",
                    "description": "Where to send it (channel name, phone, or URL).",
                },
                "message": {"type": "string"},
            },
            "required": ["channel", "target", "message"],
        },
    ),
    ToolSpec(
        name="create_calendar_event",
        description="Schedule a calendar event (meeting, review, deadline).",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "when": {"type": "string", "description": "When it occurs (free-form)."},
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional attendee identifiers.",
                },
                "notes": {"type": "string"},
            },
            "required": ["title", "when"],
        },
    ),
    ToolSpec(
        name="log_ops_event",
        description=(
            "Record an operational event (info/warning/incident) to memory for "
            "auditability. Deterministic; no escalation side effects."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": list(_OPS_SEVERITIES)},
                "title": {"type": "string"},
                "detail": {"type": "string"},
            },
            "required": ["severity", "title"],
        },
    ),
]


async def _send_notification(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return unsupported_capability(
        "Sending a notification",
        hint="No Slack/SMS/webhook provider is connected.",
    )


async def _create_calendar_event(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return unsupported_capability(
        "Creating a calendar event",
        hint="No calendar provider is connected.",
    )


async def _log_ops_event(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    severity = args["severity"]
    title = args["title"]
    detail = args.get("detail") or ""
    content = f"[{severity}] {title}"
    if detail:
        content += f"\n{detail}"
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title=f"Ops {severity}: {title}",
        content=content,
        source_task_id=task.id,
    )
    return ToolOutcome(observation=f"logged ops event [{severity}] {title[:80]}")


HANDLERS = {
    "send_notification": _send_notification,
    "create_calendar_event": _create_calendar_event,
    "log_ops_event": _log_ops_event,
}
