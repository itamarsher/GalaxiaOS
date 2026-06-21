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
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import RegistrarError
from app.integrations.dns import DnsError
from app.integrations.registry import get_registrar
from app.integrations.sitehost import SiteHost, SiteHostError
from app.models import Site, SiteDomain
from app.models.enums import SiteConnectStatus, SiteStatus
from app.services.integrations import resolve_dns_provider, resolve_site_host

# Host statuses Cloudflare Pages reports for a fully provisioned custom domain.
_LIVE_DOMAIN_STATUSES = frozenset({"active", "live"})


# ─────────────────────────────── rendering ───────────────────────────────


def slugify(text: str) -> str:
    """A short, URL/DNS-safe slug from arbitrary text."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:48] or "page"


def render_page_html(title: str, body: str) -> str:
    """Render a title + markdown-ish body into a single, self-contained HTML page.

    A minimal, dependency-free converter (headings, paragraphs, bold) — enough for
    a real landing page while keeping the only tags we emit ones we control. The
    body is HTML-escaped first, so nothing the model wrote reaches the DOM as markup.
    """
    blocks: list[str] = []
    for raw in re.split(r"\n\s*\n", (body or "").strip()):
        chunk = raw.strip()
        if not chunk:
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)$", chunk)
        if heading:
            level = len(heading.group(1)) + 1  # h2..h4
            blocks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        else:
            blocks.append(f"<p>{_inline(chunk)}</p>")
    safe_title = _html.escape(title)
    body_html = "\n    ".join(blocks)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        f"<title>{safe_title}</title>\n"
        "<style>"
        "body{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;"
        "max-width:720px;margin:0 auto;padding:48px 20px;line-height:1.6;color:#0d1320}"
        "h1{font-size:2rem;letter-spacing:-.02em}h2,h3,h4{margin-top:1.6em}"
        "</style>\n</head>\n<body>\n"
        f"    <h1>{safe_title}</h1>\n    {body_html}\n"
        "</body>\n</html>\n"
    )


def _inline(text: str) -> str:
    s = _html.escape(text)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return s.replace("\n", "<br/>")


# ─────────────────────────────── queries ───────────────────────────────


async def list_sites(db: AsyncSession, *, company_id: uuid.UUID) -> list[Site]:
    rows = await db.scalars(
        select(Site).where(Site.company_id == company_id).order_by(Site.created_at.desc())
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


# ─────────────────────────────── publish ───────────────────────────────


async def publish_site(
    db: AsyncSession, host: SiteHost, *, company_id: uuid.UUID, title: str, body: str
) -> Site:
    """Render + deploy a landing page through ``host`` and persist the :class:`Site`.

    The row is created first (``draft``) so a publish failure leaves a durable record
    with the error rather than vanishing. On success it flips to ``published`` with
    the live URL.
    """
    site = Site(
        company_id=company_id,
        slug=slugify(title),
        title=title,
        body=body,
        html=render_page_html(title, body),
        status=SiteStatus.draft,
    )
    db.add(site)
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
