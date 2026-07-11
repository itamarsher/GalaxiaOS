"""Marketing area tools: publish content, connect a domain, schedule posts, ads.

``publish_content`` (landing pages / blog) and ``connect_domain`` are REAL when the
company has saved Cloudflare credentials in Settings (bring-your-own-key): they host
a generated page and point a bought domain at it. The remaining channels
(social/email) and ``schedule_social_post`` / ``run_ad_campaign`` reach providers
that aren't wired, so they stay unsupported — each reports the capability is
unavailable and points the agent at ``request_capability`` rather than fabricating a
success that pollutes memory, metrics, and plans.
"""

from __future__ import annotations

from app.integrations.dns import DnsError
from app.integrations.sitehost import SiteHostError
from app.models import Agent, Task
from app.models.enums import DecisionKind, DecisionStatus, SiteConnectStatus
from app.models.governance import DecisionRequest
from app.providers.base import ToolSpec
from app.runtime.tools.base import (
    ToolOutcome,
    consume_approval_grant,
    unsupported_capability,
)
from app.runtime.tools.critique import visual_gate
from app.services import sites as sites_svc
from app.services.integrations import resolve_dns_provider, resolve_site_host

# Channels that publish to a real static host via the site-host seam.
_SITE_CHANNELS = {"landing_page", "blog"}

SPECS: list[ToolSpec] = [
    ToolSpec(
        name="publish_content",
        description=(
            "Publish a piece of marketing content (blog post, landing page, social "
            "post, or email) and return its published URL. The page goes live "
            "immediately on a free *.pages.dev URL — no domain purchase needed. The "
            "body supports markdown links ([text](https://…)), so you can link to a "
            "hosted waitlist/form (e.g. Tally, Typeform, Google Forms) for early "
            "signal. For a landing_page you can instead set lead_capture=true to add "
            "a built-in email/waitlist form to the page itself; submissions are "
            "stored and added to the CRM as leads automatically."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "enum": ["blog", "landing_page", "social", "email"],
                },
                "title": {"type": "string"},
                "body": {"type": "string"},
                "lead_capture": {
                    "type": "boolean",
                    "description": (
                        "landing_page only: add a built-in email capture / waitlist "
                        "form to the page. Captured emails become CRM leads."
                    ),
                },
                "cta_headline": {
                    "type": "string",
                    "description": "Heading above the capture form, e.g. 'Join the waitlist'.",
                },
                "cta_button": {
                    "type": "string",
                    "description": "Capture form button label, e.g. 'Notify me'.",
                },
            },
            "required": ["channel", "title", "body"],
        },
    ),
    ToolSpec(
        name="connect_domain",
        description=(
            "Connect a domain you own to a published landing page: create its DNS "
            "zone, point the domain at the host, and provision HTTPS. If the domain's "
            "nameservers can't be delegated automatically, the founder is asked to "
            "set them. Defaults to the most recently published site."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "site_slug": {
                    "type": "string",
                    "description": "Optional slug of the site to connect; defaults to the latest.",
                },
            },
            "required": ["domain"],
        },
    ),
    ToolSpec(
        name="schedule_social_post",
        description="Schedule a social media post for later publishing on a platform.",
        input_schema={
            "type": "object",
            "properties": {
                "platform": {"type": "string"},
                "content": {"type": "string"},
                "when": {
                    "type": "string",
                    "description": "Optional ISO timestamp / human time to publish at.",
                },
            },
            "required": ["platform", "content"],
        },
    ),
    ToolSpec(
        name="run_ad_campaign",
        description=(
            "Launch a paid ad campaign on a platform. SPENDS real budget: the "
            "amount_cents is charged through the cost meter and gated by governance."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "platform": {"type": "string"},
                "objective": {"type": "string"},
                "amount_cents": {
                    "type": "integer",
                    "description": "Budget to spend on the campaign, in cents.",
                },
            },
            "required": ["platform", "objective", "amount_cents"],
        },
    ),
]


async def _publish_content(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    channel = str(args.get("channel") or "").strip()
    if channel not in _SITE_CHANNELS:
        # social / email reach providers that aren't wired.
        return unsupported_capability(
            f"Publishing to the {channel or 'unknown'} channel",
            hint="Only landing_page and blog channels have a connected host.",
        )

    host = await resolve_site_host(db, company_id=task.company_id)
    if host is None:
        return unsupported_capability(
            "Publishing marketing content",
            hint=(
                "No website host is connected. Configure it yourself with "
                "`configure_integration` (provider 'cloudflare', a scoped api_token + "
                "account_id), or ask the founder to add Cloudflare in Settings."
            ),
        )

    title = str(args["title"]).strip()
    body = str(args["body"])
    # Lead capture is a landing-page-only affordance.
    lead_capture = bool(args.get("lead_capture")) and channel == "landing_page"
    cta_headline = (str(args.get("cta_headline")).strip() or None) if args.get("cta_headline") else None
    cta_button = (str(args.get("cta_button")).strip() or None) if args.get("cta_button") else None

    # Self-validation: an independent critic reviews the rendered page BEFORE it
    # goes live, so the fleet stops shipping ugly/off-brand pages. If it wants
    # changes (and rounds remain), the agent gets the critique and revises; the
    # page publishes only once the critic is satisfied.
    preview_html = sites_svc.render_page_html(
        title,
        body,
        form_action="#" if lead_capture else None,
        cta_headline=cta_headline,
        cta_button=cta_button,
    )
    hold = await visual_gate(
        db,
        ctx,
        agent=agent,
        task=task,
        key=f"page:{channel}",
        kind="landing page" if channel == "landing_page" else "blog page",
        brief=f"Title: {title}\nChannel: {channel}",
        html=preview_html,
    )
    if hold is not None:
        return hold

    try:
        site = await sites_svc.publish_site(
            db,
            host,
            company_id=task.company_id,
            title=title,
            body=body,
            lead_capture=lead_capture,
            cta_headline=cta_headline,
            cta_button=cta_button,
        )
    except SiteHostError as exc:
        return ToolOutcome(observation=f"publish failed: {exc}", is_error=True)

    note = ""
    if lead_capture:
        if sites_svc.lead_capture_action(site.id):
            note = (
                " It has a built-in email/waitlist form — signups are captured as "
                "CRM leads (check the CRM with crm_find_contacts)."
            )
        else:
            # No public API base URL configured, so the on-page form can't reach us.
            note = (
                " NOTE: built-in capture is unavailable (no public API URL configured), "
                "so no form was added — instead, link the page to a hosted form/waitlist "
                "(e.g. Tally or Google Forms) by re-publishing with a markdown link."
            )
    return ToolOutcome(
        observation=(
            f"published '{title}' at {site.deployment_url} (slug {site.slug}).{note} "
            "Use connect_domain to point a bought domain at it."
        )
    )


async def _connect_domain(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    domain = str(args["domain"]).strip().lower().lstrip("@").rstrip(".")
    if not domain or "." not in domain:
        return ToolOutcome(observation=f"'{domain}' is not a valid domain", is_error=True)

    host = await resolve_site_host(db, company_id=task.company_id)
    dns = await resolve_dns_provider(db, company_id=task.company_id)
    if host is None or dns is None:
        return unsupported_capability(
            "Connecting a domain to a site",
            hint=(
                "No website host is connected. Configure it yourself with "
                "`configure_integration` (provider 'cloudflare', a scoped api_token + "
                "account_id), or ask the founder to add Cloudflare in Settings."
            ),
        )

    site = await sites_svc.resolve_site(
        db, company_id=task.company_id, slug=args.get("site_slug")
    )
    if site is None or not site.project_name:
        return ToolOutcome(
            observation="no published site to connect — call publish_content first",
            is_error=True,
        )

    sd = await sites_svc.get_or_create_domain(
        db, company_id=task.company_id, domain=domain, site=site
    )
    # On resume after the founder approved the "set your nameservers" decision,
    # consume the grant so we trust the delegation instead of re-parking.
    delegated = await consume_approval_grant(db, task_id=task.id, tool="connect_domain")
    try:
        sd = await sites_svc.begin_connection(db, sd=sd, founder_delegated=delegated)
    except (DnsError, SiteHostError) as exc:
        return ToolOutcome(observation=f"connecting {domain} failed: {exc}", is_error=True)

    if sd.status == SiteConnectStatus.live:
        return ToolOutcome(observation=f"{domain} is live and serving {site.title} over HTTPS")

    # Nameservers couldn't be delegated automatically — ask the founder to point
    # the domain at Cloudflare. Park the task until they confirm (the connection
    # reconciler then finishes attaching + provisioning HTTPS).
    if sd.status == SiteConnectStatus.pending_ns and sd.nameservers:
        ns = "\n".join(f"- `{n}`" for n in sd.nameservers)
        db.add(
            DecisionRequest(
                company_id=task.company_id,
                agent_id=agent.id,
                task_id=task.id,
                kind=DecisionKind.user_action,
                summary=(
                    f"**Point `{domain}` at our DNS to go live**\n\n"
                    f"At your domain registrar, set the nameservers for `{domain}` to:\n\n"
                    f"{ns}\n\n"
                    "Approve once you've updated them — the site finishes connecting "
                    "automatically (this can take a little while to propagate)."
                ),
                payload={"tool": "connect_domain", "args": args},
                status=DecisionStatus.pending,
            )
        )
        await db.flush()
        return ToolOutcome(
            observation=(
                f"created DNS zone for {domain}; asked the founder to delegate "
                "nameservers. Connection resumes once they confirm."
            ),
            park=True,
        )

    return ToolOutcome(
        observation=(
            f"{domain} connection in progress (status: {sd.status.value}); HTTPS "
            "provisioning completes shortly."
        )
    )


async def _schedule_social_post(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return unsupported_capability(
        "Scheduling a social post",
        hint="No social-media provider is connected.",
    )


async def _run_ad_campaign(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    # Note: no budget is charged — the campaign would not actually run.
    return unsupported_capability(
        "Running an ad campaign",
        hint="No ad network is connected, so the budget was NOT charged.",
    )


HANDLERS = {
    "publish_content": _publish_content,
    "connect_domain": _connect_domain,
    "schedule_social_post": _schedule_social_post,
    "run_ad_campaign": _run_ad_campaign,
}
