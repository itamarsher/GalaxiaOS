"""Site hosting + domain connection: seam wiring, rendering, and the state machine."""

from __future__ import annotations

import uuid

import pytest

from app.integrations.dns import DnsError, Zone, get_dns_provider
from app.integrations.sitehost import SiteHostError, get_site_host
from app.models import Site
from app.models.enums import SiteConnectStatus, SiteStatus
from app.runtime.tools.marketing import _connect_domain, _publish_content
from app.services import sites as sites_svc
from tests.conftest import requires_db

# ── seam wiring (pure) ──────────────────────────────────────────────────────────


def test_site_host_wiring():
    from app.integrations.cloudflare import CloudflareSiteHost

    assert get_site_host("none") is None
    assert isinstance(get_site_host("cloudflare"), CloudflareSiteHost)
    with pytest.raises(ValueError):
        get_site_host("bogus")


def test_dns_provider_wiring():
    from app.integrations.cloudflare import CloudflareDns

    assert get_dns_provider("none") is None
    assert isinstance(get_dns_provider("cloudflare"), CloudflareDns)
    with pytest.raises(ValueError):
        get_dns_provider("bogus")


async def test_cloudflare_requires_credentials():
    # Default settings have no token/account, so every call fails loudly rather
    # than silently doing nothing.
    with pytest.raises(SiteHostError):
        await get_site_host("cloudflare").publish(slug="s", title="t", html="<p>x</p>")
    with pytest.raises(DnsError):
        await get_dns_provider("cloudflare").ensure_zone("acme.com")


# ── rendering (pure) ────────────────────────────────────────────────────────────


def test_slugify():
    assert sites_svc.slugify("Hello, World!") == "hello-world"
    assert sites_svc.slugify("") == "page"


def test_render_page_html_escapes_and_structures():
    html = sites_svc.render_page_html("My <Co>", "# Welcome\n\nWe **launch** fast.")
    assert "<title>My &lt;Co&gt;</title>" in html
    assert "<h1>My &lt;Co&gt;</h1>" in html
    assert "<h2>Welcome</h2>" in html
    assert "<strong>launch</strong>" in html


# ── tool guards (no provider wired) ─────────────────────────────────────────────


class _Task:
    """Minimal stand-in for a Task (only company_id is read on these paths)."""

    company_id = uuid.uuid4()


async def test_publish_unsupported_without_host(monkeypatch):
    async def _none(db, *, company_id):
        return None

    monkeypatch.setattr("app.runtime.tools.marketing.resolve_site_host", _none)
    out = await _publish_content(
        None, None, agent=None, task=_Task(),
        args={"channel": "landing_page", "title": "t", "body": "b"},
    )
    assert out.is_error and "not supported" in out.observation


async def test_publish_unsupported_channel():
    out = await _publish_content(
        None, None, agent=None, task=None,
        args={"channel": "social", "title": "t", "body": "b"},
    )
    assert out.is_error


async def test_connect_unsupported_without_providers(monkeypatch):
    async def _host(db, *, company_id):
        return object()

    async def _none(db, *, company_id):
        return None

    monkeypatch.setattr("app.runtime.tools.marketing.resolve_site_host", _host)
    monkeypatch.setattr("app.runtime.tools.marketing.resolve_dns_provider", _none)
    out = await _connect_domain(
        None, None, agent=None, task=_Task(), args={"domain": "acme.com"}
    )
    assert out.is_error and "not supported" in out.observation


# ── connection state machine (DB) ───────────────────────────────────────────────


class _StubDns:
    def __init__(self, zone_status="pending"):
        self._status = zone_status

    async def ensure_zone(self, domain):
        return Zone(zone_id="zone-1", nameservers=["a.ns.cloudflare.com", "b.ns.cloudflare.com"],
                    status="pending")

    async def zone_status(self, zone_id):
        return self._status

    async def upsert_record(self, **kw):
        return "rec-1"


class _StubHost:
    async def attach_domain(self, *, project, domain):
        return "active"

    async def domain_status(self, *, project, domain):
        return "active"


class _OkRegistrar:
    async def set_nameservers(self, domain, nameservers):
        return None


def _wire(monkeypatch, *, dns, host, registrar):
    async def _dns(db, *, company_id):
        return dns

    async def _host(db, *, company_id):
        return host

    monkeypatch.setattr("app.services.sites.resolve_dns_provider", _dns)
    monkeypatch.setattr("app.services.sites.resolve_site_host", _host)
    monkeypatch.setattr("app.services.sites.get_registrar", lambda: registrar)


async def _make_site(db, company_id):
    site = Site(
        company_id=company_id, slug="launch", title="Launch", body="b",
        html="<p>b</p>", status=SiteStatus.published, provider="cloudflare",
        project_name="abos-launch", deployment_url="https://abos-launch.pages.dev",
    )
    db.add(site)
    await db.flush()
    return site


@requires_db
async def test_connect_pending_ns_when_registrar_cannot_delegate(
    session_factory, company_with_budget, monkeypatch
):
    _wire(monkeypatch, dns=_StubDns("pending"), host=_StubHost(), registrar=None)
    async with session_factory() as db:
        site = await _make_site(db, company_with_budget)
        sd = await sites_svc.get_or_create_domain(
            db, company_id=company_with_budget, domain="acme.com", site=site
        )
        sd = await sites_svc.begin_connection(db, sd=sd)
        # No registrar API + zone not active yet -> founder must delegate NS.
        assert sd.status == SiteConnectStatus.pending_ns
        assert sd.nameservers == ["a.ns.cloudflare.com", "b.ns.cloudflare.com"]


@requires_db
async def test_connect_auto_delegates_then_goes_live(
    session_factory, company_with_budget, monkeypatch
):
    _wire(monkeypatch, dns=_StubDns("active"), host=_StubHost(), registrar=_OkRegistrar())
    async with session_factory() as db:
        site = await _make_site(db, company_with_budget)
        sd = await sites_svc.get_or_create_domain(
            db, company_id=company_with_budget, domain="acme.com", site=site
        )
        sd = await sites_svc.begin_connection(db, sd=sd)
        # Registrar delegated + zone active + host accepts -> live in one pass.
        assert sd.status == SiteConnectStatus.live


@requires_db
async def test_reconciler_advances_after_founder_delegation(
    session_factory, company_with_budget, monkeypatch
):
    # Founder confirmed delegation; zone now active -> reconciler drives to live.
    _wire(monkeypatch, dns=_StubDns("active"), host=_StubHost(), registrar=None)
    async with session_factory() as db:
        site = await _make_site(db, company_with_budget)
        sd = await sites_svc.get_or_create_domain(
            db, company_id=company_with_budget, domain="acme.com", site=site
        )
        sd = await sites_svc.begin_connection(db, sd=sd, founder_delegated=True)
        assert sd.status == SiteConnectStatus.live
        # And the row is no longer in the reconciler's pending set.
        pending = await sites_svc.pending_connections(db, company_id=company_with_budget)
        assert all(p.id != sd.id for p in pending)
