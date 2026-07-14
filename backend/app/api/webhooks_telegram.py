"""Inbound Telegram webhook: link a founder's chat to a company.

The shared bot (``@GalaxiaOSBot``) points here (see
``app.services.telegram.ensure_webhook``). The only update we act on is the
``/start <token>`` a founder sends by tapping the connect deep link from Settings:
the token is a short-lived, signed company reference, so a valid one attaches the
sender's chat id to that company's delegate config. Everything else is a friendly
no-op. Always returns 200 so Telegram doesn't retry.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.config import settings
from app.db import set_tenant
from app.deps import DbDep
from app.models import Company
from app.security import decode_telegram_connect_token
from app.services import delegate as delegate_svc
from app.services import telegram as telegram_svc

router = APIRouter(prefix="/webhooks/telegram", tags=["telegram"])


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
    text = (message.get("text") or "").strip()
    if chat_id is None:
        return {"ok": True}

    # Only /start <token> does anything. Bare /start (or anything else) gets help.
    if not text.startswith("/start"):
        return {"ok": True}
    parts = text.split(maxsplit=1)
    token = parts[1].strip() if len(parts) > 1 else ""
    company_id = decode_telegram_connect_token(token) if token else None
    if company_id is None:
        await telegram_svc.send_message(
            str(chat_id),
            "👋 To connect this chat, open *Settings → Autonomy & notifications* in "
            "GalaxiaOS and tap *Connect Telegram* — that link carries a secure code.",
        )
        return {"ok": True}

    await set_tenant(db, company_id)
    company = await db.get(Company, company_id)
    if company is None:
        return {"ok": True}
    await delegate_svc.link_telegram(db, company_id=company_id, chat_id=str(chat_id))
    await db.commit()
    await telegram_svc.send_message(
        str(chat_id),
        f"✅ Connected to *{company.name}*. You'll get decision notifications here.",
    )
    return {"ok": True}
