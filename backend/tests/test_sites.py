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


def test_render_page_html_renders_markdown_lists():
    html = sites_svc.render_page_html("t", "Why us:\n\n- Fast\n- **Cheap**\n- Simple")
    assert "<ul>" in html and html.count("<li>") == 3
    assert "<li>Fast</li>" in html
    assert "<li><strong>Cheap</strong></li>" in html


def test_render_page_html_degrades_authored_html_instead_of_leaking_css():
    # A model that supplies a full HTML landing page (its own <style>, hero markup)
    # must not have its CSS/markup dumped as visible page text — the scaffold is
    # stripped to readable prose first.
    body = (
        "<!doctype html><html><head><style>.hero{background:linear-gradient(#000,#fff);"
        "padding:80px}</style></head><body>"
        "<h1>Run a business in one session</h1>"
        "<p>GalaxiaOS launches your <b>autonomous</b> company.</p>"
        "<ul><li>Zero code</li><li>Real agents</li></ul>"
        "</body></html>"
    )
    html = sites_svc.render_page_html("Launch", body)
    # None of the CSS/scaffold survives as visible text.
    assert "linear-gradient" not in html
    assert "&lt;style&gt;" not in html and "<style>.hero" not in html
    assert ".hero{" not in html
    # The real copy does survive, as clean structure.
    assert "Run a business in one session" in html
    assert "<strong>autonomous</strong>" in html  # <b> normalized to markdown bold
    assert "<li>Zero code</li>" in html and "<li>Real agents</li>" in html


def test_render_page_html_leaves_ordinary_prose_with_angle_brackets_untouched():
    # A '<' in plain copy must not trigger HTML-scaffold stripping.
    html = sites_svc.render_page_html("t", "Latency is < 100ms and cost is low.")
    assert "Latency is &lt; 100ms and cost is low." in html


def test_render_page_html_renders_safe_links_only():
    html = sites_svc.render_page_html("t", "Sign up at [our form](https://tally.so/r/x).")
    assert '<a href="https://tally.so/r/x" target="_blank" rel="noopener noreferrer">our form</a>' in html
    # Non-http(s) schemes must never become a link (no javascript:/data: hrefs).
    assert "<a " not in sites_svc.render_page_html("t", "[x](javascript:alert(1))")


def test_render_page_html_capture_form_is_opt_in():
    plain = sites_svc.render_page_html("t", "b")
    assert "<form" not in plain  # the form element is only emitted with an action
    action = "https://api.example.com/p/sites/abc/subscribe"
    form = sites_svc.render_page_html("t", "b", form_action=action, cta_headline="Join", cta_button="Go")
    assert '<form class="abos-capture"' in form
    assert action in form
    assert 'name="email"' in form
    assert 'name="website"' in form  # spam honeypot
    assert ">Join</h3>" in form and ">Go</button>" in form


def test_lead_capture_action_requires_public_base_url(monkeypatch):
    sid = uuid.uuid4()
    monkeypatch.setattr(sites_svc.settings, "public_api_base_url", "")
    assert sites_svc.lead_capture_action(sid) is None
    monkeypatch.setattr(sites_svc.settings, "public_api_base_url", "https://api.example.com/")
    assert sites_svc.lead_capture_action(sid) == f"https://api.example.com/p/sites/{sid}/subscribe"


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


# ── lead capture (DB) ─────────────────────────────────────────────────────────


class _PublishHost:
    """A site host that 'publishes' to a deterministic fake URL."""

    async def publish(self, *, slug, title, html):
        from app.integrations.sitehost import HostedSite

        return HostedSite(
            url=f"https://abos-{slug}.pages.dev",
            provider="cloudflare",
            project=f"abos-{slug}",
            deployment_id="dep-1",
        )


@requires_db
async def test_publish_with_lead_capture_embeds_form(
    session_factory, company_with_budget, monkeypatch
):
    monkeypatch.setattr(sites_svc.settings, "public_api_base_url", "https://api.example.com")
    async with session_factory() as db:
        site = await sites_svc.publish_site(
            db, _PublishHost(), company_id=company_with_budget,
            title="Launch", body="Coming soon.", lead_capture=True,
        )
        await db.commit()
        assert site.status == SiteStatus.published
        # The deployed HTML carries a form posting back to this site's public sink.
        assert f"/p/sites/{site.id}/subscribe" in site.html
        assert 'class="abos-capture"' in site.html


@requires_db
async def test_capture_lead_persists_and_funnels_to_crm(
    session_factory, company_with_budget
):
    from app.services import crm as crm_svc

    async with session_factory() as db:
        site = await _make_site(db, company_with_budget)
        await db.commit()

    async with session_factory() as db:
        site = await db.get(Site, site.id)
        lead = await sites_svc.capture_lead(
            db, site=site, email="  Founder@Example.com ", name="Ann", message="excited"
        )
        await db.commit()
        assert lead.email == "Founder@Example.com"
        assert lead.source == f"landing_page:{site.slug}"

        # Stored as a durable lead…
        leads = await sites_svc.list_leads(db, company_id=company_with_budget)
        assert [le.email for le in leads] == ["Founder@Example.com"]
        counts = await sites_svc.lead_counts(db, company_id=company_with_budget)
        assert counts.get(site.id) == 1

        # …and funnelled into the CRM as a workable contact.
        contacts = await crm_svc.find_contacts(db, company_id=company_with_budget)
        assert any(c.email == "Founder@Example.com" and c.source == lead.source for c in contacts)


@requires_db
async def test_public_subscribe_endpoint_captures_and_filters(
    session_factory, company_with_budget
):
    """The visitor-facing path: a static page POSTs the form back to /p/…/subscribe."""
    import os

    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app import main
    from app.db import get_db

    async with session_factory() as db:
        site = await _make_site(db, company_with_budget)
        await db.commit()
        site_id = site.id

    async def _override_db():
        # TestClient runs the app in its own event loop, so the session must use
        # an engine created *inside* that loop (the fixture's engine is bound to
        # the test's loop — asyncpg connections can't cross loops).
        engine = create_async_engine(os.environ["ABOS_TEST_DATABASE_URL"], future=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                yield db
        finally:
            await engine.dispose()

    app = main.create_app()
    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as client:
        # Unknown page -> 404.
        assert client.post(f"/p/sites/{uuid.uuid4()}/subscribe", data={"email": "a@b.co"}).status_code == 404

        # Honeypot filled -> accepted (200) but stored nothing.
        r = client.post(
            f"/p/sites/{site_id}/subscribe",
            data={"email": "bot@spam.co", "website": "http://spam"},
        )
        assert r.status_code == 200

        # Invalid email -> 400, nothing stored.
        assert client.post(f"/p/sites/{site_id}/subscribe", data={"email": "nope"}).status_code == 400

        # A real signup -> 200 and a confirmation page.
        r = client.post(f"/p/sites/{site_id}/subscribe", data={"email": "real@example.com", "name": "Ann"})
        assert r.status_code == 200
        assert "on the list" in r.text.lower()

    # Exactly one lead was stored despite the bot/invalid attempts.
    async with session_factory() as db:
        leads = await sites_svc.list_leads(db, company_id=company_with_budget)
        assert [le.email for le in leads] == ["real@example.com"]


@requires_db
async def test_capture_lead_dedupes_repeat_signups_in_crm(
    session_factory, company_with_budget
):
    from app.services import crm as crm_svc

    async with session_factory() as db:
        site = await _make_site(db, company_with_budget)
        await db.commit()

    async with session_factory() as db:
        site = await db.get(Site, site.id)
        await sites_svc.capture_lead(db, site=site, email="dup@example.com")
        await sites_svc.capture_lead(db, site=site, email="dup@example.com")
        await db.commit()
        # Two raw signals are both recorded…
        assert len(await sites_svc.list_leads(db, company_id=company_with_budget)) == 2
        # …but the CRM keeps a single contact (upsert by email).
        contacts = await crm_svc.find_contacts(db, company_id=company_with_budget, query="dup@example.com")
        assert len(contacts) == 1
