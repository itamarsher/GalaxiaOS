"""Automatic Resend → Cloudflare email DNS setup."""

from __future__ import annotations

import pytest

from app.integrations.dns import DnsError
from app.integrations.email import EmailError
from app.integrations.resend_domains import ResendDomain, ResendRecord
from app.services import email_setup as svc

# ── name normalization (pure) ─────────────────────────────────────────────────


def test_fqdn_normalizes_relative_absolute_and_apex():
    assert svc.fqdn("send", "acme.com") == "send.acme.com"
    assert svc.fqdn("resend._domainkey", "acme.com") == "resend._domainkey.acme.com"
    # Already absolute (with or without trailing dot) is left as-is.
    assert svc.fqdn("send.acme.com", "acme.com") == "send.acme.com"
    assert svc.fqdn("send.acme.com.", "acme.com") == "send.acme.com"
    # Apex markers map to the domain itself.
    assert svc.fqdn("@", "acme.com") == "acme.com"
    assert svc.fqdn("", "acme.com") == "acme.com"


# ── orchestration (stubbed Resend + DNS) ──────────────────────────────────────


def _rec(**kw):
    base = dict(
        record="SPF",
        type="TXT",
        name="send",
        value="v",
        priority=None,
        ttl="Auto",
        status="not_started",
    )
    base.update(kw)
    return ResendRecord(**base)


_RECORDS = [
    _rec(record="SPF", type="MX", name="send", value="feedback-smtp.example.com", priority=10),
    _rec(record="SPF", type="TXT", name="send", value="v=spf1 include:amazonses.com ~all"),
    _rec(record="DKIM", type="CNAME", name="resend._domainkey", value="x.dkim.amazonses.com"),
]


class _StubResend:
    def __init__(self):
        self.verified = False

    async def create_or_get(self, name):
        return ResendDomain(id="dom_1", name=name, status="pending", records=_RECORDS)

    async def verify(self, domain_id):
        self.verified = True

    async def get(self, domain_id):
        return ResendDomain(id=domain_id, name="acme.com", status="verifying", records=_RECORDS)


class _StubZone:
    zone_id = "zone-1"


class _StubDns:
    def __init__(self):
        self.writes = []

    async def ensure_zone(self, domain):
        return _StubZone()

    async def upsert_record(self, *, zone_id, type, name, content, proxied=True, priority=None):
        self.writes.append({"type": type, "name": name, "proxied": proxied, "priority": priority})
        return "rec-1"


def _wire(monkeypatch, *, key="re_test", dns):
    async def _key(db, *, company_id, provider):
        return key

    async def _dns(db, *, company_id):
        return dns

    monkeypatch.setattr(svc.apikeys, "get_plaintext_key", _key)
    monkeypatch.setattr(svc, "resolve_dns_provider", _dns)


async def test_configure_writes_all_records_and_verifies(monkeypatch):
    dns = _StubDns()
    resend = _StubResend()
    _wire(monkeypatch, dns=dns)
    monkeypatch.setattr(svc, "ResendDomains", lambda key: resend)

    result = await svc.configure_sender_dns(None, company_id=None, domain="ACME.com")

    assert result.domain == "acme.com"
    assert result.all_written is True
    assert resend.verified is True
    # Records are written to Cloudflare as FQDNs, never proxied, MX carries priority.
    by_type = {w["type"]: w for w in dns.writes}
    assert by_type["MX"]["name"] == "send.acme.com" and by_type["MX"]["priority"] == 10
    assert by_type["TXT"]["name"] == "send.acme.com"
    assert by_type["CNAME"]["name"] == "resend._domainkey.acme.com"
    assert all(w["proxied"] is False for w in dns.writes)


async def test_configure_requires_resend_key(monkeypatch):
    _wire(monkeypatch, key=None, dns=_StubDns())
    with pytest.raises(EmailError, match="No Resend key"):
        await svc.configure_sender_dns(None, company_id=None, domain="acme.com")


async def test_configure_requires_cloudflare(monkeypatch):
    _wire(monkeypatch, dns=None)
    monkeypatch.setattr(svc, "ResendDomains", lambda key: _StubResend())
    with pytest.raises(DnsError, match="Cloudflare isn't connected"):
        await svc.configure_sender_dns(None, company_id=None, domain="acme.com")


async def test_configure_reports_partial_failures(monkeypatch):
    class _FlakyDns(_StubDns):
        async def upsert_record(self, *, zone_id, type, name, content, proxied=True, priority=None):
            if type == "CNAME":
                raise DnsError("zone busy")
            return await super().upsert_record(
                zone_id=zone_id,
                type=type,
                name=name,
                content=content,
                proxied=proxied,
                priority=priority,
            )

    _wire(monkeypatch, dns=_FlakyDns())
    monkeypatch.setattr(svc, "ResendDomains", lambda key: _StubResend())
    result = await svc.configure_sender_dns(None, company_id=None, domain="acme.com")
    assert result.all_written is False
    failed = [r for r in result.records if not r.ok]
    assert len(failed) == 1 and failed[0].type == "CNAME" and "zone busy" in failed[0].error


# ── status poll ───────────────────────────────────────────────────────────────


async def test_email_status_reports_not_configured_without_key(monkeypatch):
    async def _no_key(db, *, company_id, provider):
        return None

    monkeypatch.setattr(svc.apikeys, "get_plaintext_key", _no_key)
    res = await svc.email_status(None, company_id=None, domain="acme.com")
    assert res.configured is False and res.status == "not_configured"


async def test_email_status_lists_pending_records(monkeypatch):
    async def _key(db, *, company_id, provider):
        return "re_test"

    monkeypatch.setattr(svc.apikeys, "get_plaintext_key", _key)

    records = [
        _rec(type="TXT", name="send", status="verified"),
        _rec(type="CNAME", name="resend._domainkey", status="not_started"),
    ]

    class _Resend:
        async def find(self, name):
            return ResendDomain(id="d1", name=name, status="pending", records=records)

    monkeypatch.setattr(svc, "ResendDomains", lambda key: _Resend())
    res = await svc.email_status(None, company_id=None, domain="acme.com")
    assert res.configured is True and res.status == "pending"
    # Only the unverified record is pending, as an FQDN.
    assert res.pending == ["resend._domainkey.acme.com"]
