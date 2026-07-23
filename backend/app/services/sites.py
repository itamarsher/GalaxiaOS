"""Sites service — host a generated landing page and connect a bought domain.

The persistence and orchestration behind two agent tools (``publish_content`` and
``connect_domain``) and the connection reconciler job. Everything is tenant-scoped:
callers pass the ``company_id`` from the runtime context and queries never cross
that boundary (RLS is the second line of defence).

Provider I/O goes through the seams (:func:`~app.integrations.sitehost.get_site_host`,
:func:`~app.integrations.dns.get_dns_provider`,
:func:`~app.integrations.registry.get_registrar`); when a seam is unconfigured the
callers report the capability is unsupported rather than faking a result.
"""

from __future__ import annotations

import html as _html
import logging
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.config import settings
from app.db import set_tenant
from app.integrations.base import RegistrarError
from app.integrations.dns import DnsError
from app.integrations.registry import get_registrar
from app.integrations.sitehost import SiteHost, SiteHostError
from app.models import Site, SiteDomain, SiteLead
from app.models.enums import SiteConnectStatus, SiteStatus
from app.services.integrations import resolve_dns_provider, resolve_site_host

logger = logging.getLogger("app")

# Host statuses Cloudflare Pages reports for a fully provisioned custom domain.
_LIVE_DOMAIN_STATUSES = frozenset({"active", "live"})

# Default copy for the built-in capture form when the agent doesn't override it.
_DEFAULT_CTA_HEADLINE = "Join the waitlist"
_DEFAULT_CTA_BUTTON = "Notify me"


# ─────────────────────────────── rendering ───────────────────────────────


def slugify(text: str) -> str:
    """A short, URL/DNS-safe slug from arbitrary text."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:48] or "page"


# Shared page chrome — the GalaxiaOS brand look, so a published page matches the app.
# Kept inline (single self-contained static asset, no external stylesheet or font) and
# token-driven, mirroring the app's design system (frontend/app/globals.css): deep
# midnight base with the logo's indigo accent and white-on-indigo CTAs. Uses a radial
# indigo glow (never ``linear-gradient``/``.hero{``, which the HTML-scaffold guard
# strips from authored bodies) so the chrome renders identically whatever the agent wrote.
_PAGE_STYLE = (
    ":root{--bg:#0d1320;--bg-glow:#161a36;--panel:#151d2e;--border:#27324a;--text:#e7edf6;"
    "--muted:#8b99b2;--accent:#6366f1;--accent-strong:#a5b4fc;--accent-soft:rgba(99,102,241,0.14);"
    "--on-accent:#ffffff;--radius:14px;--radius-sm:9px}"
    "*{box-sizing:border-box}"
    "body{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,"
    "sans-serif;max-width:660px;margin:0 auto;padding:80px 22px 104px;line-height:1.65;"
    "color:var(--text);background:var(--bg);background-image:radial-gradient(1200px 600px at "
    "50% -10%,var(--bg-glow),transparent 70%);background-attachment:fixed;"
    "-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}"
    "h1{font-size:clamp(2.15rem,6vw,3rem);line-height:1.08;letter-spacing:-.03em;font-weight:800;"
    "color:#fff;margin:0 0 .5em}"
    "h2{font-size:1.55rem;line-height:1.25;letter-spacing:-.02em;font-weight:700;color:#fff;"
    "margin:2.4em 0 .5em}"
    "h3{font-size:1.15rem;font-weight:700;color:#fff;margin:1.8em 0 .4em}"
    "p{margin:0 0 1.15em;font-size:1.075rem;color:var(--text)}"
    "ul{padding-left:1.15em;margin:0 0 1.25em}li{margin:.4em 0}"
    "a{color:var(--accent-strong);text-decoration:none;font-weight:600}a:hover{text-decoration:underline}"
    "strong{color:#fff;font-weight:700}"
    ".abos-capture{margin-top:2.6em;padding:28px;border:1px solid var(--border);"
    "border-radius:var(--radius);background:var(--panel);"
    "box-shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.25)}"
    ".abos-capture h3{margin:0 0 14px;font-size:1.2rem}"
    ".abos-capture input[type=email]{width:100%;padding:13px 15px;font-size:16px;color:var(--text);"
    "border:1px solid var(--border);border-radius:var(--radius-sm);box-sizing:border-box;"
    "background:#0c111c}"
    ".abos-capture input[type=email]:focus{outline:none;border-color:var(--accent);"
    "box-shadow:0 0 0 3px var(--accent-soft)}"
    ".abos-capture button{margin-top:12px;width:100%;padding:13px 18px;font-size:16px;"
    "font-weight:700;color:var(--on-accent);background:var(--accent);border:0;"
    "border-radius:var(--radius-sm);cursor:pointer;transition:filter .15s ease}"
    ".abos-capture button:hover{filter:brightness(1.08)}"
    ".abos-hp{position:absolute;left:-9999px;width:1px;height:1px;opacity:0}"
)


def _page(title: str, body_html: str) -> str:
    safe_title = _html.escape(title)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        f"<title>{safe_title}</title>\n"
        f"<style>{_PAGE_STYLE}</style>\n</head>\n<body>\n"
        f"    <h1>{safe_title}</h1>\n    {body_html}\n"
        "</body>\n</html>\n"
    )


# A body that looks like a hand-authored HTML document rather than markdown. A
# capable model, told to build a "landing page", often writes a full page with its
# own <style>/<div>/hero markup — which, escaped verbatim, would dump raw CSS/HTML
# as visible text on the page (that's the failure this guards against).
_HTML_DOC_RE = re.compile(r"<!doctype|<html[\s>]|<head[\s>]|<style[\s>]|<body[\s>]", re.I)
# Blocks whose *contents* must be dropped entirely (not just untagged) — showing
# CSS or JS source as page copy is the exact bug we're fixing.
_DROP_BLOCK_RE = re.compile(r"<(script|style|head)\b[^>]*>.*?</\1>", re.I | re.S)


def _strip_html_scaffold(body: str) -> str:
    """Reduce an HTML-authored body to clean text the markdown renderer can handle.

    The renderer intentionally emits only tags it controls, so raw HTML is escaped
    to text. When a model supplies a whole HTML document, that escaping turns its
    ``<style>`` and markup into visible source on the page. Rather than leak that,
    drop ``<script>/<style>/<head>`` blocks outright and unwrap the remaining tags
    to their text — degrading a full page to readable prose instead of CSS soup.
    Only applied when the body actually looks like HTML, so genuine markdown (and
    the ``<`` characters that appear in ordinary prose) is left untouched.
    """
    if not _HTML_DOC_RE.search(body):
        return body
    text = _DROP_BLOCK_RE.sub("\n", body)
    # Container closings → blank line, so each becomes its own markdown block.
    text = re.sub(r"</(p|div|section|header|footer|article|h[1-6]|ul|ol)\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    # Headings open a new block with the matching markdown prefix.
    text = re.sub(r"<h[1-2]\b[^>]*>", "\n\n## ", text, flags=re.I)
    text = re.sub(r"<h[3-6]\b[^>]*>", "\n\n### ", text, flags=re.I)
    # List items become consecutive "- " lines (single newline keeps them one list).
    text = re.sub(r"</li\s*>", "", text, flags=re.I)
    text = re.sub(r"<li\b[^>]*>", "\n- ", text, flags=re.I)
    text = re.sub(r"</?(strong|b|em|i)\b[^>]*>", "**", text, flags=re.I)  # keep emphasis
    text = re.sub(r"<[^>]+>", "", text)  # drop any remaining tags
    text = _html.unescape(text)  # &amp; → & etc., so re-escaping later is clean
    # Collapse the runs of blank lines the stripping leaves behind.
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def render_page_html(
    title: str,
    body: str,
    *,
    form_action: str | None = None,
    cta_headline: str | None = None,
    cta_button: str | None = None,
) -> str:
    """Render a title + markdown-ish body into a single, self-contained HTML page.

    A minimal, dependency-free converter (headings, lists, paragraphs, bold, and
    links) — enough for a real landing page while keeping the only tags we emit ones
    we control. The body is HTML-escaped first, so nothing the model wrote reaches
    the DOM as markup; links are only emitted for ``http(s)`` URLs. A body that is
    itself an HTML document is first reduced to text (see ``_strip_html_scaffold``)
    so its CSS/markup can't leak onto the page as visible source.

    When ``form_action`` is given, an email/waitlist capture form that POSTs there
    is appended — turning the page into an early-signal capture page with no domain
    or third-party tool required.
    """
    body = _strip_html_scaffold((body or "").strip())
    blocks: list[str] = []
    list_items: list[str] = []

    def _flush_list() -> None:
        if list_items:
            blocks.append("<ul>\n      " + "\n      ".join(list_items) + "\n    </ul>")
            list_items.clear()

    for raw in re.split(r"\n\s*\n", body):
        chunk = raw.strip()
        if not chunk:
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)$", chunk)
        if heading:
            _flush_list()
            level = len(heading.group(1)) + 1  # h2..h4
            blocks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        # A block of consecutive "- "/"* " lines becomes a single list.
        lines = chunk.splitlines()
        if lines and all(re.match(r"^\s*[-*]\s+\S", ln) for ln in lines):
            for ln in lines:
                item = re.sub(r"^\s*[-*]\s+", "", ln)
                list_items.append(f"<li>{_inline(item)}</li>")
            _flush_list()
        else:
            _flush_list()
            blocks.append(f"<p>{_inline(chunk)}</p>")
    _flush_list()
    if form_action:
        blocks.append(
            _capture_form_html(
                action=form_action,
                headline=cta_headline or _DEFAULT_CTA_HEADLINE,
                button=cta_button or _DEFAULT_CTA_BUTTON,
            )
        )
    return _page(title, "\n    ".join(blocks))


def render_thanks_html(*, site_title: str, back_url: str | None) -> str:
    """The page a visitor sees after submitting the capture form."""
    back = (
        f'<p><a href="{_html.escape(back_url)}">&larr; Back to {_html.escape(site_title)}</a></p>'
        if back_url
        else ""
    )
    body = f"<p>Thanks — you're on the list. We'll be in touch.</p>\n    {back}"
    return _page("You're on the list", body)


def render_page_invalid_email(*, site_title: str, back_url: str | None) -> str:
    """Shown when the submitted address doesn't look like an email."""
    back = (
        f'<p><a href="{_html.escape(back_url)}">&larr; Back to {_html.escape(site_title)}</a></p>'
        if back_url
        else ""
    )
    body = f"<p>That doesn't look like a valid email — please go back and try again.</p>\n    {back}"
    return _page("Check your email address", body)


# Links first (the model writes `[text](https://…)`), then bold, then newlines.
# Restricting the scheme to http(s) keeps `javascript:`/`data:` URIs out of href.
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


def _inline(text: str) -> str:
    s = _html.escape(text)
    s = _LINK_RE.sub(r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return s.replace("\n", "<br/>")


def _capture_form_html(*, action: str, headline: str, button: str) -> str:
    return (
        f'<form class="abos-capture" method="post" action="{_html.escape(action)}">\n'
        f"      <h3>{_html.escape(headline)}</h3>\n"
        # Honeypot: a hidden field real users never fill but bots do. Submissions
        # with it set are accepted (no error shown) and dropped server-side.
        '      <input type="text" name="website" class="abos-hp" tabindex="-1"'
        ' autocomplete="off" aria-hidden="true"/>\n'
        '      <input type="email" name="email" required placeholder="you@email.com"'
        ' aria-label="Email address"/>\n'
        f"      <button type=\"submit\">{_html.escape(button)}</button>\n"
        "    </form>"
    )


def lead_capture_action(site_id: uuid.UUID) -> str | None:
    """Absolute URL the static page's capture form POSTs to, or None.

    Returns None when ``ABOS_PUBLIC_API_BASE_URL`` isn't configured — the page is
    hosted on a third-party origin, so without an absolute URL back to this API the
    form can't reach us and native capture is disabled.
    """
    base = (settings.public_api_base_url or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/p/sites/{site_id}/subscribe"


# ─────────────────────────────── queries ───────────────────────────────


async def list_sites(db: AsyncSession, *, company_id: uuid.UUID) -> list[Site]:
    # ``SiteOut`` exposes only metadata, so don't load every page's ``body``
    # markdown and rendered ``html`` Text columns (tens of KB each) just to drop
    # them — defer them and let the detail view pull them when actually needed.
    rows = await db.scalars(
        select(Site)
        .options(defer(Site.body), defer(Site.html))
        .where(Site.company_id == company_id)
        .order_by(Site.created_at.desc())
    )
    return list(rows)


async def latest_published_site(db: AsyncSession, *, company_id: uuid.UUID) -> Site | None:
    return await db.scalar(
        select(Site)
        .where(Site.company_id == company_id, Site.status == SiteStatus.published)
        .order_by(Site.created_at.desc())
    )


async def resolve_site(
    db: AsyncSession, *, company_id: uuid.UUID, slug: str | None
) -> Site | None:
    """The site matching ``slug`` (most recent), or the latest published site."""
    if slug:
        return await db.scalar(
            select(Site)
            .where(Site.company_id == company_id, Site.slug == slugify(slug))
            .order_by(Site.created_at.desc())
        )
    return await latest_published_site(db, company_id=company_id)


# ─────────────────────────────── leads ───────────────────────────────


async def get_site_by_id(db: AsyncSession, site_id: uuid.UUID) -> Site | None:
    """Fetch a site by id without a tenant filter — for the PUBLIC capture endpoint.

    The capture form is submitted by anonymous visitors with no auth/company
    context, so the site is looked up by its (unguessable) id and the tenant is
    derived from the row. Callers should :func:`~app.db.set_tenant` before writing.
    """
    return await db.get(Site, site_id)


async def capture_lead(
    db: AsyncSession,
    *,
    site: Site,
    email: str,
    name: str | None = None,
    message: str | None = None,
) -> SiteLead:
    """Record an early-signal signup from a landing page and funnel it into the CRM.

    The :class:`SiteLead` row is the durable record of raw signups; the CRM contact
    (best-effort) is what the sales/growth agents actually work. Scopes the session
    to the site's tenant first so the RLS policy admits the writes.
    """
    company_id = site.company_id
    await set_tenant(db, company_id)
    # Generic label: the site's channel (landing_page vs blog) isn't tracked on the
    # row, and a hardcoded "landing_page:" prefix would mislabel blog-captured leads.
    source = f"site:{site.slug}"
    lead = SiteLead(
        company_id=company_id,
        site_id=site.id,
        email=email.strip()[:320],
        name=(name.strip()[:255] if name and name.strip() else None),
        message=(message.strip() if message and message.strip() else None),
        source=source,
    )
    db.add(lead)
    await db.flush()

    # Funnel into the CRM so the lead shows up where agents look for pipeline.
    # Best-effort: a CRM hiccup must not lose the signal we already persisted.
    try:
        from app.services import crm as crm_svc

        await crm_svc.upsert_contact(
            db,
            company_id=company_id,
            email=lead.email,
            name=lead.name,
            source=source,
            note=lead.message,
        )
    except Exception:  # noqa: BLE001
        logger.warning("CRM funnel for site lead failed; lead row kept", exc_info=True)
    return lead


async def list_leads(
    db: AsyncSession, *, company_id: uuid.UUID, site_id: uuid.UUID | None = None, limit: int = 500
) -> list[SiteLead]:
    stmt = select(SiteLead).where(SiteLead.company_id == company_id)
    if site_id is not None:
        stmt = stmt.where(SiteLead.site_id == site_id)
    stmt = stmt.order_by(SiteLead.created_at.desc()).limit(max(1, min(limit, 1000)))
    return list((await db.scalars(stmt)).all())


async def lead_counts(db: AsyncSession, *, company_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """Map of site_id -> number of captured leads, for the company's sites list."""
    rows = await db.execute(
        select(SiteLead.site_id, func.count())
        .where(SiteLead.company_id == company_id, SiteLead.site_id.isnot(None))
        .group_by(SiteLead.site_id)
    )
    return {sid: n for sid, n in rows.all() if sid is not None}


# ─────────────────────────────── publish ───────────────────────────────


async def publish_site(
    db: AsyncSession,
    host: SiteHost,
    *,
    company_id: uuid.UUID,
    title: str,
    body: str,
    lead_capture: bool = False,
    cta_headline: str | None = None,
    cta_button: str | None = None,
) -> Site:
    """Render + deploy a landing page through ``host`` and persist the :class:`Site`.

    The row is created first (``draft``) so a publish failure leaves a durable record
    with the error rather than vanishing. On success it flips to ``published`` with
    the live URL.

    With ``lead_capture`` the rendered page carries a built-in email/waitlist form
    that POSTs back to this API (so signups need no domain or third-party tool). The
    form's action embeds the site id, so the HTML is rendered after the row is
    flushed and has one.
    """
    site = Site(
        company_id=company_id,
        slug=slugify(title),
        title=title,
        body=body,
        status=SiteStatus.draft,
    )
    db.add(site)
    await db.flush()

    form_action = lead_capture_action(site.id) if lead_capture else None
    site.html = render_page_html(
        title, body, form_action=form_action, cta_headline=cta_headline, cta_button=cta_button
    )
    await db.flush()

    try:
        hosted = await host.publish(slug=site.slug, title=title, html=site.html)
    except SiteHostError as exc:
        site.status = SiteStatus.failed
        site.last_error = str(exc)
        await db.flush()
        raise

    site.provider = hosted.provider
    site.project_name = hosted.project
    site.deployment_url = hosted.url
    site.status = SiteStatus.published
    site.last_error = None
    await db.flush()

    # Best-effort: keep a copy of the published page in the company's Artifacts
    # folder so every deliverable lands in the external store. Never fails the
    # publish — no-ops silently when no file provider is connected.
    from app.models.enums import FileCategory
    from app.services import files as files_svc

    await files_svc.safe_archive(
        db,
        company_id=company_id,
        category=FileCategory.artifact,
        name=f"{site.slug}.html",
        content=site.html or "",
        mime_type="text/html",
        description=f"Published landing page: {title}"
        + (f" ({site.deployment_url})" if site.deployment_url else ""),
    )
    return site


# ─────────────────────────────── connect domain ───────────────────────────────


async def get_or_create_domain(
    db: AsyncSession, *, company_id: uuid.UUID, domain: str, site: Site
) -> SiteDomain:
    row = await db.scalar(
        select(SiteDomain).where(
            SiteDomain.company_id == company_id, SiteDomain.domain == domain
        )
    )
    if row is None:
        row = SiteDomain(
            company_id=company_id,
            site_id=site.id,
            domain=domain,
            status=SiteConnectStatus.pending_ns,
        )
        db.add(row)
        await db.flush()
    elif row.site_id != site.id:
        row.site_id = site.id
        await db.flush()
    return row


async def begin_connection(
    db: AsyncSession, *, sd: SiteDomain, founder_delegated: bool = False
) -> SiteDomain:
    """Create the DNS zone and attempt nameserver delegation at the registrar.

    Leaves ``sd`` in ``ns_set`` when the registrar delegated automatically (or the
    founder confirmed they did it, ``founder_delegated``), or in ``pending_ns`` (with
    ``nameservers`` recorded) when the founder must point the domain at Cloudflare
    manually. Then advances as far as it can.
    """
    dns = await resolve_dns_provider(db, company_id=sd.company_id)
    if dns is None:
        raise DnsError("No DNS provider is configured for this company.")
    zone = await dns.ensure_zone(sd.domain)
    sd.zone_id = zone.zone_id
    sd.nameservers = zone.nameservers
    sd.provider = "cloudflare"

    if founder_delegated:
        # The founder approved the "set your nameservers" decision; trust it and
        # let activation polling confirm. Avoids re-parking the resumed task.
        sd.status = SiteConnectStatus.ns_set
    else:
        registrar = get_registrar()
        if registrar is not None:
            try:
                await registrar.set_nameservers(sd.domain, zone.nameservers)
                sd.status = SiteConnectStatus.ns_set
            except RegistrarError as exc:
                # Registrar can't delegate via API — the founder must do it. Keep
                # pending_ns; the caller surfaces the nameservers as a decision.
                sd.last_error = str(exc)
    await db.flush()
    return await advance_connection(db, sd=sd)


async def advance_connection(db: AsyncSession, *, sd: SiteDomain) -> SiteDomain:
    """Push one connection forward as far as the providers currently allow.

    Idempotent and safe to call repeatedly (the tool after delegation, and the
    reconciler on a schedule). Provider errors are recorded in ``last_error`` and the
    status is left in place so the next pass retries, rather than failing hard.
    """
    dns = await resolve_dns_provider(db, company_id=sd.company_id)
    host = await resolve_site_host(db, company_id=sd.company_id)
    if dns is None or host is None or not sd.zone_id:
        return sd

    site = await db.get(Site, sd.site_id) if sd.site_id else None
    project = site.project_name if site else None

    try:
        if sd.status in (SiteConnectStatus.pending_ns, SiteConnectStatus.ns_set):
            if await dns.zone_status(sd.zone_id) == "active":
                sd.status = SiteConnectStatus.zone_active

        if sd.status == SiteConnectStatus.zone_active and project:
            await host.attach_domain(project=project, domain=sd.domain)
            await dns.upsert_record(
                zone_id=sd.zone_id,
                type="CNAME",
                name=sd.domain,
                content=f"{project}.pages.dev",
                proxied=True,
            )
            sd.status = SiteConnectStatus.attaching

        if sd.status == SiteConnectStatus.attaching and project:
            status = await host.domain_status(project=project, domain=sd.domain)
            if status.lower() in _LIVE_DOMAIN_STATUSES:
                sd.status = SiteConnectStatus.live
        sd.last_error = None
    except (DnsError, SiteHostError) as exc:
        # Provider hiccup — record it and leave the status in place so the next
        # pass (tool resume or reconciler) retries rather than failing hard.
        sd.last_error = str(exc)
    await db.flush()
    return sd


async def pending_connections(db: AsyncSession, *, company_id: uuid.UUID) -> list[SiteDomain]:
    """Domains still working toward ``live`` (for the reconciler)."""
    rows = await db.scalars(
        select(SiteDomain).where(
            SiteDomain.company_id == company_id,
            SiteDomain.status.notin_(
                [SiteConnectStatus.live, SiteConnectStatus.failed, SiteConnectStatus.pending_ns]
            ),
        )
    )
    return list(rows)
