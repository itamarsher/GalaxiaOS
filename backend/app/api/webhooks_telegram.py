"""Inbound Telegram webhook: connect a founder's chat, and route their replies.

The shared bot (``@GalaxiaOSBot``) points here (see
``app.services.telegram.ensure_webhook``). Two things happen here:

* ``/start <token>`` — the founder taps the connect deep link from Settings; the
  token is a short-lived, signed company reference, so a valid one attaches the
  sender's chat id to that company's delegate config.
* any other text — treated as a **reply to the decision the delegate notified
  them about**: it's routed through the *same* resolution path an in-app reply
  uses (approve / reject / ask to clarify), and the bot reacts 👍 on the founder's
  message to acknowledge receipt.

Always returns 200 so Telegram doesn't retry. All Telegram sends are best-effort.
"""

from __future__ import annotations

import html

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.config import settings
from app.db import set_tenant
from app.deps import DbDep
from app.models import Company, DecisionRequest
from app.models.enums import DecisionStatus
from app.runtime.queue import enqueue_task
from app.security import decode_telegram_connect_token
from app.services import decisions as decisions_svc
from app.services import delegate as delegate_svc
from app.services import telegram as telegram_svc

router = APIRouter(prefix="/webhooks/telegram", tags=["telegram"])


async def _handle_connect(db: DbDep, chat_id: int, text: str) -> None:
    """``/start <token>`` — link this chat to the company the token references."""
    parts = text.split(maxsplit=1)
    token = parts[1].strip() if len(parts) > 1 else ""
    company_id = decode_telegram_connect_token(token) if token else None
    if company_id is None:
        await telegram_svc.send_message(
            str(chat_id),
            "👋 To connect this chat, open <b>Settings → Notifications</b> in "
            "GalaxiaOS and tap <b>Connect Telegram</b> — that link carries a secure code.",
        )
        return
    await set_tenant(db, company_id)
    company = await db.get(Company, company_id)
    if company is None:
        return
    await delegate_svc.link_telegram(db, company_id=company_id, chat_id=str(chat_id))
    await db.commit()
    await telegram_svc.send_message(
        str(chat_id),
        f"✅ Connected to <b>{html.escape(company.name)}</b>. You'll get decision "
        "notifications here — reply to one to approve or reject it.",
    )


async def _pending_decisions(db: DbDep, company_id) -> list[DecisionRequest]:
    """The company's open, resolvable decisions (newest first)."""
    rows = await db.scalars(
        select(DecisionRequest)
        .where(
            DecisionRequest.company_id == company_id,
            DecisionRequest.status == DecisionStatus.pending,
            DecisionRequest.task_id.isnot(None),
            DecisionRequest.channel_id.isnot(None),
        )
        .order_by(DecisionRequest.created_at.desc())
    )
    return list(rows.all())


def _inbox_url(company_id) -> str | None:
    web = settings.web_base_url.rstrip("/") if settings.web_base_url else ""
    return f"{web}/c/{company_id}" if web else None


async def _handle_reply(db: DbDep, chat_id: int, message_id: int | None, text: str) -> None:
    """A plain message → resolve the founder's pending decision and ack with 👍."""
    company_id = await delegate_svc.company_for_telegram_chat(db, str(chat_id))
    if company_id is None:
        await telegram_svc.send_message(
            str(chat_id),
            "This chat isn't linked to a company yet. Open <b>Settings → "
            "Notifications</b> in GalaxiaOS and tap <b>Connect Telegram</b>.",
        )
        return

    await set_tenant(db, company_id)
    pendings = await _pending_decisions(db, company_id)

    resumed = None
    verdict = "none"
    if len(pendings) == 1:
        resumed, verdict = await decisions_svc.try_resolve_from_reply(
            db,
            company_id=company_id,
            channel_id=pendings[0].channel_id,
            reply=text,
            user_id=None,
        )
    await db.commit()

    # Side effects only after the DB is durably committed (mirrors the triage cron).
    if message_id:
        await telegram_svc.set_reaction(str(chat_id), message_id, "👍")
    if resumed is not None:
        await enqueue_task(resumed)

    if not pendings:
        await telegram_svc.send_message(
            str(chat_id), "Nothing is waiting on you right now. 👍"
        )
    elif len(pendings) > 1:
        url = _inbox_url(company_id)
        tail = f' <a href="{html.escape(url)}">Open the inbox</a> to choose.' if url else ""
        await telegram_svc.send_message(
            str(chat_id),
            f"You have <b>{len(pendings)}</b> decisions waiting — I can't tell which "
            f"this answers from here.{tail}",
        )
    elif verdict == "unclear":
        await telegram_svc.send_message(
            str(chat_id),
            "Got your reply, but I couldn't tell if that's a yes or no. Reply "
            "<b>Approve</b> or <b>Reject</b> (you can add a reason).",
        )


@router.post("")
async def telegram_update(request: Request, db: DbDep) -> dict:
    # Verify the update really came from Telegram (the secret we set on the webhook).
    if settings.telegram_webhook_secret:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != settings.telegram_webhook_secret:
            return {"ok": True}  # silently drop spoofed calls

    try:
        update = await request.json()
    except Exception:
        return {"ok": True}

    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    text = (message.get("text") or "").strip()
    if chat_id is None or not text:
        return {"ok": True}

    try:
        if text.startswith("/start"):
            await _handle_connect(db, chat_id, text)
        else:
            await _handle_reply(db, chat_id, message_id, text)
    except Exception:
        # Never fail the webhook — the in-app inbox is always the source of truth.
        return {"ok": True}
    return {"ok": True}
