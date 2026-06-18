"""Email seam — how agents send mail (sales, marketing, ops, support).

A Protocol plus two real, credential-gated adapters:

- :class:`SmtpEmailSender` — vendor-agnostic; speaks plain SMTP over ``smtplib``
  in a worker thread, so it works with Gmail, SES, Mailgun, Postmark, etc.
  without adding a dependency. Credential-gated (``ABOS_SMTP_*`` +
  ``ABOS_EMAIL_FROM``).
- :class:`~app.integrations.resend.ResendEmailSender` — the Resend HTTP API,
  chosen for its **generous free tier** (3,000 emails/month, 100/day) and
  first-class **custom-domain** support, so an autonomous business can mail from
  ``hello@yourstartup.com`` at $0. Credential-gated (``ABOS_RESEND_API_KEY`` +
  ``ABOS_EMAIL_FROM``).

Without creds the real adapters raise :class:`EmailError` rather than attempting
to send. There is deliberately NO simulated sender: faking a sent email would
let agents believe outreach happened when it did not. When no provider is
configured (``ABOS_EMAIL_PROVIDER`` defaults to ``simulated``/unset),
:func:`get_email_sender` returns ``None`` and the ``send_email`` tool reports the
capability is unsupported. Enable real send with ``ABOS_EMAIL_PROVIDER=smtp`` or
``ABOS_EMAIL_PROVIDER=resend``.
"""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol, runtime_checkable

from app.config import settings


@dataclass(frozen=True)
class EmailResult:
    message_id: str
    provider: str


class EmailError(RuntimeError):
    """Raised when an email cannot be sent (missing creds, SMTP error)."""


@runtime_checkable
class EmailSender(Protocol):
    async def send(self, *, to: str, subject: str, body: str) -> EmailResult:
        """Send an email. Raises :class:`EmailError` on failure."""
        ...


class SmtpEmailSender:
    """Real, vendor-agnostic SMTP sender (credential-gated)."""

    def _require_config(self) -> str:
        if not settings.smtp_host:
            raise EmailError("SMTP host missing (set ABOS_SMTP_HOST).")
        if not settings.email_from:
            raise EmailError("Sender address missing (set ABOS_EMAIL_FROM).")
        return settings.email_from

    def _send_sync(self, msg: EmailMessage) -> None:
        timeout = settings.web_search_timeout_seconds
        if settings.smtp_use_tls:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout) as smtp:
                smtp.starttls()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout) as smtp:
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(msg)

    async def send(self, *, to: str, subject: str, body: str) -> EmailResult:
        sender = self._require_config()
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            # smtplib is blocking; run it off the event loop.
            await asyncio.to_thread(self._send_sync, msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailError(f"SMTP send failed: {exc}") from exc
        return EmailResult(message_id=msg["Message-ID"] or f"smtp:{to}", provider="smtp")


def get_email_sender(name: str | None = None) -> EmailSender | None:
    """Return the configured email sender, or ``None`` if none is wired.

    There is no simulated fallback: an unconfigured environment returns ``None`` so
    the ``send_email`` tool reports the capability is unsupported instead of
    pretending mail was sent.
    """
    key = (name or settings.email_provider).strip().lower()
    if key in ("", "none", "simulated"):
        return None
    if key == "smtp":
        return SmtpEmailSender()
    if key == "resend":
        from app.integrations.resend import ResendEmailSender

        return ResendEmailSender()
    raise ValueError(f"unknown email provider: {key!r}")
