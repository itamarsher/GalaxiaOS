"""Resend email adapter — REAL email delivery (credential-gated).

Resend is a developer-first email API with a **generous free tier** (3,000
emails/month, 100/day) and first-class **custom-domain** support: you add your
domain, drop in the SPF/DKIM DNS records it generates, and then send ``From:``
addresses on that domain — exactly what an autonomous business needs to mail
from ``hello@yourstartup.com`` rather than a shared sandbox address. This makes
it the lowest-friction way to get ABOS sending branded mail at $0.

The API key comes from settings (``ABOS_RESEND_API_KEY``) and the sender from
``ABOS_EMAIL_FROM``; without them :meth:`send` raises :class:`EmailError`
rather than hitting the network. The single HTTP shape is parsed by the pure
:meth:`_parse_response` staticmethod so success/error mapping is unit-testable
offline.

Off by default (``ABOS_EMAIL_PROVIDER=simulated``). Enable with
``ABOS_EMAIL_PROVIDER=resend`` plus a key and a verified-domain ``From``
address.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.integrations.email import EmailError, EmailResult

_ENDPOINT = "https://api.resend.com/emails"


class ResendEmailSender:
    """Real email sender backed by the Resend API (credential-gated)."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        sender: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.resend_api_key
        self._sender = sender if sender is not None else settings.email_from
        self._timeout = timeout if timeout is not None else settings.web_search_timeout_seconds

    def _require_config(self) -> tuple[str, str]:
        if not self._api_key:
            raise EmailError("Resend API key missing (set ABOS_RESEND_API_KEY).")
        if not self._sender:
            raise EmailError("Sender address missing (set ABOS_EMAIL_FROM).")
        return self._api_key, self._sender

    async def send(self, *, to: str, subject: str, body: str) -> EmailResult:
        api_key, sender = self._require_config()
        payload = {"from": sender, "to": [to], "subject": subject, "text": body}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    _ENDPOINT,
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                data = resp.json() if resp.content else {}
        except httpx.HTTPError as exc:
            raise EmailError(f"Resend request failed: {exc}") from exc
        except ValueError as exc:  # non-JSON body
            raise EmailError(f"Resend returned non-JSON: {exc}") from exc
        return self._parse_response(resp.status_code, data)

    @staticmethod
    def _parse_response(status_code: int, body: dict) -> EmailResult:
        """Map Resend's ``{"id": ...}`` (or ``{"message": ...}`` error) response.

        Resend returns ``200`` with ``{"id": "<uuid>"}`` on success and a 4xx
        with ``{"statusCode", "name", "message"}`` on failure. We surface the
        vendor message verbatim so a bad ``From`` domain or rate-limit reads
        clearly in the agent transcript.
        """
        if status_code >= 400 or "id" not in body:
            message = body.get("message") or body.get("name") or f"HTTP {status_code}"
            raise EmailError(f"Resend send failed: {message}")
        return EmailResult(message_id=str(body["id"]), provider="resend")
