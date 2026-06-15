"""Operations (OPS) tools: notifications, calendar events, and ops logging.

Area-specific tools for the operations function of an autonomous business. Every
handler here is deterministic and SIMULATED — no network calls, no new config —
so the runtime stays reproducible. The package ``__init__`` auto-discovers the
``SPECS`` / ``HANDLERS`` exports, so no central registry edits are needed.

Email lives in the core ``send_email`` tool; this module covers the non-email
notification channels (slack/sms/webhook) plus lightweight calendar and ops-event
bookkeeping that logs to Company Memory for auditability and recall.
"""

from __future__ import annotations

import hashlib

from app.models import Agent, Task
from app.models.enums import MemoryType
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome
from app.services import memory as memory_svc

_NOTIFY_CHANNELS = ("slack", "sms", "webhook")
_OPS_SEVERITIES = ("info", "warning", "incident")


def _deterministic_id(prefix: str, *parts: str) -> str:
    """A stable, network-free id derived from its inputs.

    Same inputs always yield the same id, which keeps simulated side effects
    reproducible across runs (and easy to assert in tests).
    """
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:16]}"


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="send_notification",
        description=(
            "Send a non-email notification (Slack message, SMS, or webhook). "
            "Simulated and deterministic; for email use the send_email tool."
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
        description=(
            "Schedule a calendar event (meeting, review, deadline). Simulated and "
            "deterministic; returns a stable event id."
        ),
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
    channel = args["channel"]
    target = args["target"]
    message = args["message"]
    notif_id = _deterministic_id("notif", str(task.company_id), channel, target, message)
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title=f"Notify {channel}:{target}"[:500],
        content=message[:2000],
        source_task_id=task.id,
    )
    return ToolOutcome(
        observation=f"notification sent via {channel} to {target} (id {notif_id})"
    )


async def _create_calendar_event(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    title = args["title"]
    when = args["when"]
    attendees = args.get("attendees") or []
    notes = args.get("notes") or ""
    event_id = _deterministic_id("evt", str(task.company_id), title, when)
    lines = [f"When: {when}"]
    if attendees:
        lines.append("Attendees: " + ", ".join(str(a) for a in attendees))
    if notes:
        lines.append(f"Notes: {notes}")
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.decision,
        title=f"Event: {title} @ {when}"[:500],
        content="\n".join(lines)[:2000],
        source_task_id=task.id,
    )
    return ToolOutcome(
        observation=f"calendar event '{title[:60]}' scheduled for {when} (id {event_id})"
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
        title=f"Ops {severity}: {title}"[:500],
        content=content[:2000],
        source_task_id=task.id,
    )
    return ToolOutcome(observation=f"logged ops event [{severity}] {title[:80]}")


HANDLERS = {
    "send_notification": _send_notification,
    "create_calendar_event": _create_calendar_event,
    "log_ops_event": _log_ops_event,
}
