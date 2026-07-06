"""External-communication indexing.

One small registry decides which agent tools talk to the *outside world* and how
to read a message out of their arguments. The native agent loop calls into here
at its tool chokepoint to (a) record every external message it attempts and (b)
let the governance engine gate them with a single ``{"is_external": true}`` rule.

Keeping the classifier here — rather than scattered booleans in the runtime —
means "is this tool an external communication?" has exactly one answer, shared by
the indexer, the policy matcher, and any future channel that gets wired up.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ExternalMessage
from app.models.enums import ExternalMessageStatus


def _truncate(value: object | None, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _email(args: dict) -> dict:
    return {
        "channel": "email",
        "recipient": _truncate(args.get("to"), 500),
        "subject": _truncate(args.get("subject"), 500),
        "body": _truncate(args.get("body"), 10000),
    }


def _publish(args: dict) -> dict:
    # Only the social/email channels actually leave the company; blog/landing are
    # public the moment they're hosted, so all four count as external publishing.
    channel = str(args.get("channel") or "content").strip() or "content"
    return {
        "channel": channel,
        "recipient": None,
        "subject": _truncate(args.get("title"), 500),
        "body": _truncate(args.get("body"), 10000),
    }


def _social(args: dict) -> dict:
    return {
        "channel": "social",
        "recipient": _truncate(args.get("platform"), 500),
        "subject": None,
        "body": _truncate(args.get("content"), 10000),
    }


def _ad(args: dict) -> dict:
    return {
        "channel": "ad",
        "recipient": _truncate(args.get("platform"), 500),
        "subject": _truncate(args.get("objective"), 500),
        "body": _truncate(args.get("objective"), 10000),
    }


def _notification(args: dict) -> dict:
    return {
        "channel": "notification",
        "recipient": _truncate(args.get("channel") or args.get("to"), 500),
        "subject": _truncate(args.get("subject"), 500),
        "body": _truncate(args.get("message") or args.get("body"), 10000),
    }


#: tool name -> extractor turning the tool's args into an indexable message. The
#: keys are the single source of truth for "what is an external communication".
_EXTRACTORS: dict[str, Callable[[dict], dict]] = {
    "send_email": _email,
    "publish_content": _publish,
    "schedule_social_post": _social,
    "run_ad_campaign": _ad,
    "send_notification": _notification,
}


def is_external_comm(tool: str) -> bool:
    """True if ``tool`` sends a message outside the company."""
    return tool in _EXTRACTORS


def describe(tool: str, args: dict | None) -> dict:
    """Normalize a tool call into ``{channel, recipient, subject, body}``."""
    extractor = _EXTRACTORS.get(tool)
    return extractor(args or {}) if extractor else {"channel": "other"}


def summarize(tool: str, args: dict | None) -> str:
    """A founder-facing Markdown summary of an outbound message, for the approval
    decision (so the discussion thread carries the full context to weigh)."""
    d = describe(tool, args)
    lines = [f"**Outbound {d.get('channel', 'message')} — approval needed**", ""]
    if d.get("recipient"):
        lines.append(f"**To:** {d['recipient']}")
    if d.get("subject"):
        lines.append(f"**Subject:** {d['subject']}")
    body = (d.get("body") or "").strip()
    if body:
        preview = body if len(body) <= 1200 else body[:1200] + "…"
        lines.append("")
        lines.append(preview)
    return "\n".join(lines)


async def record(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    tool: str,
    args: dict | None,
    status: ExternalMessageStatus,
    decision_id: uuid.UUID | None = None,
    detail: str | None = None,
) -> ExternalMessage:
    """Index one external message. Flushed (not committed) so it shares the
    caller's transaction with the gate/execution it's recording."""
    d = describe(tool, args)
    msg = ExternalMessage(
        company_id=company_id,
        agent_id=agent_id,
        task_id=task_id,
        decision_id=decision_id,
        tool=tool,
        channel=d.get("channel") or "other",
        recipient=d.get("recipient"),
        subject=d.get("subject"),
        body=d.get("body"),
        payload=args if isinstance(args, dict) else None,
        status=status,
        detail=_truncate(detail, 4000),
    )
    db.add(msg)
    await db.flush()
    return msg


async def finalize(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    tool: str,
    args: dict | None,
    sent: bool,
    detail: str | None = None,
) -> ExternalMessage:
    """Record the outcome of an executed external send.

    If the message was previously parked as ``pending_approval`` on this task
    (i.e. the founder approved it and the task resumed), the existing row is moved
    to its terminal state instead of inserting a duplicate; otherwise a fresh row
    is indexed. Either way the index ends with exactly one row per real attempt.
    """
    status = ExternalMessageStatus.sent if sent else ExternalMessageStatus.failed
    pending: ExternalMessage | None = None
    if task_id is not None:
        pending = await db.scalar(
            select(ExternalMessage)
            .where(
                ExternalMessage.task_id == task_id,
                ExternalMessage.tool == tool,
                ExternalMessage.status == ExternalMessageStatus.pending_approval,
            )
            .order_by(ExternalMessage.created_at.asc())
            .limit(1)
        )
    if pending is not None:
        pending.status = status
        pending.detail = _truncate(detail, 4000)
        await db.flush()
        return pending
    return await record(
        db,
        company_id=company_id,
        agent_id=agent_id,
        task_id=task_id,
        tool=tool,
        args=args,
        status=status,
        detail=detail,
    )


async def mark_decision_resolved(
    db: AsyncSession, *, decision_id: uuid.UUID, approved: bool
) -> None:
    """When a founder rejects an external-comm decision, move its parked message
    to ``rejected`` so the index reflects that nothing was (or will be) sent.

    Approvals are intentionally left as ``pending_approval`` here: the message is
    only truly resolved once the resumed task actually attempts the send, at which
    point :func:`finalize` flips it to ``sent``/``failed``.
    """
    if approved:
        return
    msg = await db.scalar(
        select(ExternalMessage).where(ExternalMessage.decision_id == decision_id)
    )
    if msg is not None and msg.status == ExternalMessageStatus.pending_approval:
        msg.status = ExternalMessageStatus.rejected


async def list_messages(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    status: ExternalMessageStatus | None = None,
    limit: int = 200,
) -> list[ExternalMessage]:
    stmt = (
        select(ExternalMessage)
        .where(ExternalMessage.company_id == company_id)
        .order_by(ExternalMessage.created_at.desc())
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(ExternalMessage.status == status)
    return list((await db.scalars(stmt)).all())
