"""Shared-bot Telegram delivery for the founder decision delegate.

One platform bot (``@GalaxiaOSBot``, token in ``settings.telegram_bot_token``)
serves every founder — a founder *connects* by tapping a ``/start <token>`` deep
link, and we store only their chat id per company (no per-user bot, no per-company
secret). This module is the thin Telegram-API client: send a message, resolve the
bot username, register the inbound webhook, and format a decision for chat.

All calls are best-effort — Telegram being down or a bad chat id must never break
the fleet (the in-app inbox is always the source of truth).
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.observability import get_logger

_log = get_logger("app.telegram")
_API = "https://api.telegram.org"

# Cached bot username (from getMe) so we don't re-fetch it per connect link.
_bot_username: str | None = None


def enabled() -> bool:
    return bool(settings.telegram_bot_token)


def _url(method: str) -> str:
    return f"{_API}/bot{settings.telegram_bot_token}/{method}"


async def send_message(chat_id: str, text: str) -> bool:
    """Send Markdown text to a chat. Best-effort; returns success."""
    if not enabled() or not chat_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                _url("sendMessage"),
                json={
                    "chat_id": chat_id,
                    "text": text[:4000],
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
            )
        return resp.status_code < 400
    except Exception:
        return False


async def bot_username() -> str | None:
    """The bot's ``@username`` (for building connect deep links), cached."""
    global _bot_username
    if _bot_username or not enabled():
        return _bot_username
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(_url("getMe"))
        _bot_username = resp.json().get("result", {}).get("username")
    except Exception:
        return None
    return _bot_username


async def ensure_webhook(public_api_base_url: str) -> None:
    """Point the bot at our inbound endpoint so ``/start`` links resolve. Idempotent
    and best-effort — called once at startup when a token + public URL are set."""
    if not enabled() or not public_api_base_url:
        return
    url = f"{public_api_base_url.rstrip('/')}/webhooks/telegram"
    payload: dict = {"url": url, "allowed_updates": ["message"]}
    if settings.telegram_webhook_secret:
        payload["secret_token"] = settings.telegram_webhook_secret
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(_url("setWebhook"), json=payload)
        _log.info("telegram setWebhook -> %s (%s)", url, resp.status_code)
    except Exception as exc:  # noqa: BLE001
        _log.warning("telegram setWebhook failed: %s", type(exc).__name__)


def format_decision(payload: dict) -> str:
    """Render a delegate decision payload as a Telegram message."""
    needs_you = payload.get("needs_you")
    head = "🔸 *Needs your approval*" if needs_you else "✅ *Handled by your delegate*"
    lines = [
        f"{head} — {payload.get('company_name', 'your company')}",
        f"_{payload.get('kind')}_ from {payload.get('agent') or 'an agent'}",
        payload.get("summary") or "",
    ]
    if not needs_you and payload.get("delegate_rationale"):
        lines.append(f"↳ {payload['delegate_rationale']}")
    if needs_you and payload.get("inbox_url"):
        lines.append(f"[Open the decision inbox]({payload['inbox_url']})")
    return "\n".join(line for line in lines if line)
