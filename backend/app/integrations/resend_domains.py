"""Resend Domains API — register a sending domain and read its required DNS records.

Sending branded mail from ``hello@yourstartup.com`` needs the domain authenticated
with SPF/DKIM (and ideally DMARC). Resend's Domains API mints those records; this
client creates/looks up the domain, returns the records, and triggers verification.
:mod:`app.services.email_setup` then writes the records into the company's
Cloudflare zone automatically, so the founder configures nothing by hand.

Credential-gated by the company's BYOK Resend key (same key used to send). The
single HTTP shape is parsed by pure helpers so the mapping is unit-testable
offline. Not exercised against the live API in this repo.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import settings
from app.integrations.email import EmailError

_BASE = "https://api.resend.com/domains"


@dataclass(frozen=True)
class ResendRecord:
    record: str  # "SPF" | "DKIM" | "DMARC" — the auth role (for display)
    type: str  # "MX" | "TXT" | "CNAME"
    name: str  # host as Resend returns it (may be relative or absolute)
    value: str  # record content
    priority: int | None  # MX only
    ttl: str | None
    status: str  # per-record verification, e.g. "not_started" | "verified"


@dataclass(frozen=True)
class ResendDomain:
    id: str
    name: str
    status: str  # "not_started" | "pending" | "verified" | "failed" | …
    records: list[ResendRecord]


def _to_record(raw: dict) -> ResendRecord:
    priority = raw.get("priority")
    return ResendRecord(
        record=str(raw.get("record") or ""),
        type=str(raw.get("type") or "").upper(),
        name=str(raw.get("name") or ""),
        value=str(raw.get("value") or ""),
        priority=int(priority) if priority not in (None, "") else None,
        ttl=str(raw["ttl"]) if raw.get("ttl") not in (None, "") else None,
        status=str(raw.get("status") or "not_started"),
    )


def _to_domain(raw: dict) -> ResendDomain:
    return ResendDomain(
        id=str(raw.get("id") or ""),
        name=str(raw.get("name") or ""),
        status=str(raw.get("status") or "unknown"),
        records=[_to_record(r) for r in raw.get("records") or []],
    )


class ResendDomains:
    def __init__(self, api_key: str | None = None, *, timeout: float | None = None) -> None:
        self._api_key = api_key if api_key is not None else settings.resend_api_key
        self._timeout = timeout if timeout is not None else settings.web_search_timeout_seconds

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise EmailError("Resend API key missing (set ABOS_RESEND_API_KEY or attach one).")
        return {"Authorization": f"Bearer {self._api_key}"}

    async def _request(self, method: str, path: str, *, json: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(
                    method, f"{_BASE}{path}", headers=self._headers(), json=json
                )
                body = resp.json() if resp.content else {}
        except httpx.HTTPError as exc:
            raise EmailError(f"Resend request failed: {exc}") from exc
        except ValueError as exc:
            raise EmailError(f"Resend returned non-JSON: {exc}") from exc
        if resp.status_code >= 400:
            message = body.get("message") or body.get("name") or f"HTTP {resp.status_code}"
            raise EmailError(f"Resend domains error: {message}")
        return body

    async def find(self, name: str) -> ResendDomain | None:
        """Return the existing Resend domain for ``name`` (with records), or None."""
        listing = await self._request("GET", "")
        for raw in listing.get("data") or []:
            if str(raw.get("name", "")).lower() == name.lower() and raw.get("id"):
                # The list view omits records; fetch the full object for them.
                return await self.get(str(raw["id"]))
        return None

    async def create_or_get(self, name: str) -> ResendDomain:
        """Return the existing Resend domain for ``name`` or create it (with records)."""
        existing = await self.find(name)
        if existing is not None:
            return existing
        created = await self._request("POST", "", json={"name": name})
        return _to_domain(created)

    async def get(self, domain_id: str) -> ResendDomain:
        return _to_domain(await self._request("GET", f"/{domain_id}"))

    async def verify(self, domain_id: str) -> None:
        await self._request("POST", f"/{domain_id}/verify")
