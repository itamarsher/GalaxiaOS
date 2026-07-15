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

import html

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
    """Send an HTML-formatted message to a chat. Best-effort; returns success.

    Uses ``parse_mode=HTML`` (not legacy ``Markdown``): the messages embed
    agent-authored text that routinely contains ``*``, ``_`` and ``[`` — invalid
    Markdown entities that make Telegram reject the whole message with a 400 that
    this best-effort path then swallows, so the founder is never notified. HTML
    mode only reserves ``< > &``, and :func:`format_decision` escapes every dynamic
    field, so the message can't fail to parse. Callers building HTML must escape
    any dynamic text themselves (see :func:`format_decision`)."""
    if not enabled() or not chat_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                _url("sendMessage"),
                json={
                    "chat_id": chat_id,
                    "text": text[:4000],
                    "parse_mode": "HTML",
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
    """Render a delegate decision payload as an HTML Telegram message.

    Every interpolated value is HTML-escaped: the summary/rationale is
    agent-authored and the company/agent names are user data, so unescaped ``< > &``
    (or stray Markdown, under the old ``Markdown`` mode) would break parsing and the
    message would silently never send. Only the fixed scaffolding uses tags."""
    esc = html.escape
    needs_you = payload.get("needs_you")
    head = (
        "🔸 <b>Needs your approval</b>" if needs_you else "✅ <b>Handled by your delegate</b>"
    )
    lines = [
        f"{head} — {esc(str(payload.get('company_name') or 'your company'))}",
        f"<i>{esc(str(payload.get('kind') or 'decision'))}</i> from "
        f"{esc(str(payload.get('agent') or 'an agent'))}",
        esc(str(payload.get("summary") or "")),
    ]
    if not needs_you and payload.get("delegate_rationale"):
        lines.append(f"↳ {esc(str(payload['delegate_rationale']))}")
    if needs_you and payload.get("inbox_url"):
        lines.append(f'<a href="{esc(str(payload["inbox_url"]))}">Open the decision inbox</a>')
    return "\n".join(line for line in lines if line)
