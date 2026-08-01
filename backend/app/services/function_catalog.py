"""The Business-Function catalog — the reusable building blocks of a company.

Every business of the same shape needs the same building blocks: a website,
social, outbound/inbound demand, a brand, customer service, legal, finance, and so
on. RFC 0002 reframes onboarding around *these* instead of an opaque, LLM-designed
"fleet of agents": the founder **picks the functions** to implement and
auto-improve, and GalaxiaOS spins up each one's components and owns the improving
loop.

Each :class:`BusinessFunction` maps one block to how it's staffed (an existing
:class:`AgentRole`; ``custom`` for finer-grained blocks so several coexist), the
``provision_fleet``-shaped spec GalaxiaOS spins up (:func:`spec_for`), the seed
skill playbooks, and the real metric signals that define it improving
(:func:`health_signals`) — the target the cross-company improvement cycle reads.
Pure data + helpers (no I/O), shared by the picker (``api/functions.py``) and the
improvement cycle. It maps only onto *existing* roles on purpose (a new
``AgentRole`` is a migration); a block without a dedicated role is a ``custom``
agent carrying its own identity.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import AgentRole


@dataclass(frozen=True)
class BusinessFunction:
    """One reusable building block of a business (RFC 0002)."""

    key: str  # stable building-block id, e.g. "website"
    title: str  # founder-facing + agent display name
    category: str  # picker grouping: acquisition | brand | revenue | operations | oversight
    summary: str  # one-line, founder-facing description
    responsibility: str  # seed for the staffing agent's system prompt
    role: AgentRole  # which existing role staffs it (custom → its own identity)
    health_signals: tuple[str, ...] = ()  # metrics the improvement cycle reads to pick the next move
    default_skills: tuple[str, ...] = ()  # skill-library playbooks to seed
    # "in_house" (default): GalaxiaOS runs it with its own agents + native tools, no
    # third-party signup. "external": reserved for the genuinely-hard case (billing).
    implementation: str = "in_house"
    core: bool = False  # oversight GalaxiaOS always guarantees — not an à-la-carte pick


def _f(**kw) -> BusinessFunction:
    return BusinessFunction(**kw)


# Selectable blocks the founder picks from, then the oversight blocks GalaxiaOS
# guarantees on every company (appended by :func:`resolve_selection`).
_CATALOG: tuple[BusinessFunction, ...] = (
    _f(key="website", title="Web Presence & Conversion", category="acquisition",
       summary="Own the marketing site and turn visitors into signups.",
       responsibility="Own the company's website: keep it live and on-message, and continuously improve visitor-to-signup conversion.",
       role=AgentRole.custom,
       health_signals=("website_visitors", "signup_conversion_rate", "bounce_rate"),
       default_skills=("landing-page-optimization", "seo-keyword-strategy", "blog-post-production")),
    _f(key="social", title="Social Media", category="acquisition",
       summary="Grow and engage an audience across social channels.",
       responsibility="Own the company's social presence: plan and publish content, grow the audience, and lift engagement.",
       role=AgentRole.custom,
       health_signals=("social_followers", "social_engagement_rate", "social_reach"),
       default_skills=("social-media-campaign", "content-marketing-calendar", "social-graphics-batch")),
    _f(key="outbound", title="Outbound Sales", category="acquisition",
       summary="Prospect, reach out, and book meetings that create pipeline.",
       responsibility="Own outbound demand: build target lists, run personalized outreach, and book qualified meetings that create pipeline.",
       role=AgentRole.custom,
       health_signals=("outbound_meetings_booked", "outbound_reply_rate", "pipeline_created"),
       default_skills=("cold-email-outreach", "sales-followup-cadence", "deal-pipeline-review")),
    _f(key="inbound", title="Inbound & Lead Qualification", category="acquisition",
       summary="Capture, qualify, and route inbound leads fast.",
       responsibility="Own inbound demand: capture leads, qualify them quickly, and route the good ones to the right next step.",
       role=AgentRole.custom,
       health_signals=("inbound_leads", "lead_qualification_rate", "inbound_response_time"),
       default_skills=("inbound-lead-qualification", "landing-page-optimization")),
    _f(key="brand", title="Brand & Creative", category="brand",
       summary="Own the visual identity, positioning, and on-brand creative.",
       responsibility="Own the company's brand: keep the visual identity and positioning consistent and deliver on-brand creative for every channel.",
       role=AgentRole.design,
       health_signals=("brand_consistency_score", "creative_assets_delivered"),
       default_skills=("brand-identity-kit", "positioning-and-messaging", "logo-and-visual-assets")),
    _f(key="customer_service", title="Customer Service", category="revenue",
       summary="Onboard, support, and retain customers.",
       responsibility="Own the customer relationship after the sale: onboard new customers, resolve issues fast, and reduce churn.",
       role=AgentRole.custom,
       health_signals=("csat", "first_response_time", "churn_rate"),
       default_skills=("customer-onboarding-flow", "churn-reduction-playbook", "nps-and-testimonial-collection")),
    _f(key="engineering", title="Engineering", category="operations",
       summary="Build and ship the product's code, self-hosted (no GitHub).",
       responsibility="Own the product's code: implement changes, run tests, and ship reviewed diffs. Work in a sandbox against the company's bundle-backed repo (RFC 0003) — clone the repo, make the change, and push a new bundle; get founder approval on the diff before pushing when your autonomy requires it.",
       role=AgentRole.custom,
       health_signals=("code_tasks_shipped", "ci_pass_rate", "review_turnaround_hours"),
       default_skills=("deploy-and-release-ops", "bug-triage-and-escalation", "prd-writing")),
    _f(key="legal", title="Legal & Compliance", category="operations",
       summary="Flag legal risk and keep contracts and compliance in order.",
       responsibility="Own legal and compliance: review contracts, flag risk before it lands, and keep the company compliant.",
       role=AgentRole.custom,
       health_signals=("contracts_reviewed", "compliance_issues_open"),
       default_skills=("legal-risk-flagging", "contract-negotiation-prep", "compliance-check-workflow")),
    _f(key="finance", title="Finance", category="operations",
       summary="Own budget, runway, and unit economics.",
       responsibility="Own budget monitoring, runway, and unit economics.",
       role=AgentRole.finance,
       health_signals=("runway_months", "gross_margin", "burn_rate"),
       default_skills=("monthly-financial-close", "runway-and-burn-analysis", "unit-economics-analysis")),
    _f(key="billing", title="Billing & Payments", category="revenue",
       summary="Charge customers and manage subscriptions and invoices.",
       responsibility="Own billing: charge customers, manage subscriptions and invoices, and reconcile payments.",
       role=AgentRole.custom, implementation="external",  # payments → a connected provider (Stripe)
       health_signals=("mrr", "failed_payment_rate", "collections_outstanding"),
       default_skills=("invoicing-and-collections", "revenue-recognition", "stripe")),
    # ── Oversight: guaranteed on every company, not an à-la-carte pick ──────────
    _f(key="ceo", title="CEO", category="oversight",
       summary="Decompose the mission into initiatives and dispatch the team.",
       responsibility="Own strategy: decompose the mission into initiatives and dispatch them to the team.",
       role=AgentRole.ceo, core=True),
    _f(key="governance", title="Governance", category="oversight",
       summary="Own safety, compliance, and oversight.",
       responsibility="Own safety, compliance, and oversight.",
       role=AgentRole.governance, core=True),
    _f(key="auditor", title="Auditor", category="oversight",
       summary="Keep the financial records audited and the paper trail accurate.",
       responsibility="Keep the financial records audited and the invoice/receipt paper trail accurate.",
       role=AgentRole.auditor, core=True),
    _f(key="data", title="Data", category="oversight",
       summary="Own data access internally and what's shared externally.",
       responsibility="Own the company's data: make sure every internal agent can reach the data it needs, and control what is shared outside the company.",
       role=AgentRole.data, core=True),
    _f(key="platform", title="Platform Engineer", category="oversight",
       summary="Turn unmet needs into precise tracker issues.",
       responsibility="Stay dormant until another agent reports a bug or requests a capability; then turn it into a precise tracker issue so the platform can be fixed or extended.",
       role=AgentRole.platform, core=True),
)

_BY_KEY: dict[str, BusinessFunction] = {f.key: f for f in _CATALOG}


def all_functions() -> tuple[BusinessFunction, ...]:
    """The full catalog, selectable blocks first then guaranteed oversight."""
    return _CATALOG


def selectable_functions() -> list[BusinessFunction]:
    """The building blocks a founder picks from (excludes guaranteed oversight)."""
    return [f for f in _CATALOG if not f.core]


#: The lean default set of business functions a company starts with when the plan
#: recommends none — a general go-to-market + operations core. NOT a fixed roster of
#: agents: each of these functions provisions and owns its own staffing agent (RFC
#: 0002), and the guaranteed oversight blocks are appended by ``resolve_selection``.
_DEFAULT_SELECTION: tuple[str, ...] = (
    "website",
    "outbound",
    "inbound",
    "customer_service",
    "brand",
    "finance",
)


def default_selection() -> list[str]:
    """The default set of function keys when a plan recommends none (self-staffing)."""
    return list(_DEFAULT_SELECTION)


def core_functions() -> list[BusinessFunction]:
    """Oversight blocks GalaxiaOS guarantees on every company regardless of picks."""
    return [f for f in _CATALOG if f.core]


def get(key: str) -> BusinessFunction | None:
    """Look up one building block by its stable key, or ``None``."""
    return _BY_KEY.get(key)


def is_in_house(key: str) -> bool:
    """Whether GalaxiaOS runs this block itself (no third-party signup required).

    In-house-first is strategic: keep functions native so a founder isn't forced to
    register for a dozen services. Only ``external`` blocks (e.g. billing) need a
    connected provider — the seam onboarding uses to prompt for a connection."""
    fn = _BY_KEY.get(key)
    return fn is None or fn.implementation == "in_house"


def health_signals(key: str) -> tuple[str, ...]:
    """The metric-signal names that define this function improving (empty if none)."""
    fn = _BY_KEY.get(key)
    return fn.health_signals if fn else ()  # unknown key → no target


def function_config(fn: BusinessFunction) -> dict:
    """Per-function metadata to persist on the provisioned agent's ``config`` (JSONB).

    Lets the improvement cycle (slice 3) recover which function an agent staffs and
    its health target without a schema change, and marks `external` blocks so the
    connect-prompt can find them after launch."""
    return {
        "function": fn.key,
        "implementation": fn.implementation,
        "health_signals": list(fn.health_signals),
        "default_skills": list(fn.default_skills),
    }


def _responsibility_for(fn: BusinessFunction) -> str:
    """The staffing agent's system-prompt seed, with its health target baked in.

    Anchoring the health signals (and, for `external` blocks, the connected-provider
    note) into the prompt is what makes the agent operate toward its KPIs from day one."""
    text = fn.responsibility
    if fn.health_signals:
        text += ("\n\nYour health metrics — what \"improving\" means for this function: "
                 + ", ".join(fn.health_signals) + ".")
    if fn.implementation == "external":
        text += (" This function runs on a connected external provider; coordinate that "
                 "connection before operating.")
    return text


def spec_for(key: str) -> dict:
    """A ``provision_fleet``-compatible spec for one block (raises ``KeyError`` if unknown).

    The seam where "GalaxiaOS spins up the component" maps onto existing
    org-provisioning: the dict is shaped exactly like the org-designer /
    spec dicts ``onboarding.provision_fleet`` consumes (plus a
    ``config`` blob it now passes through), so a founder's pick provisions through
    one code path — carrying the function's identity, health target, and skills.
    """
    fn = _BY_KEY[key]
    return {
        "role": fn.role.value,
        "name": fn.title,
        "responsibility": _responsibility_for(fn),
        "autonomy_level": "approve_required",
        "config": function_config(fn),
    }


def external_functions(keys: list[str]) -> list[str]:
    """Which selected keys need a connected provider (not in-house) — the connect-prompt.

    In-house-first means most functions need nothing; only ``external`` blocks (e.g.
    billing → Stripe) are surfaced for the founder to connect. Core/unknown ignored."""
    return [k for k in keys if (fn := _BY_KEY.get(k)) is not None and not fn.core
            and fn.implementation == "external"]


def recommendation_directive() -> str:
    """Prompt block telling the mission→plan LLM to recommend functions from the catalog.

    Appended to ``MISSION_TO_PLAN_SYSTEM`` at call time so the catalog stays the one
    source of the vocabulary. In-house-first is stated so the model prefers native
    blocks and only reaches for an `external` one (billing) when the business needs it."""
    lines = "\n".join(f"- {f.key}: {f.summary}" for f in selectable_functions())
    return (
        "\n\nAlso return \"recommended_functions\": an array of catalog keys for the "
        "building blocks THIS mission needs, most important first. Keep it in-house "
        "first — prefer the native blocks below; only add \"billing\" when the business "
        "must charge customers itself. Do NOT list oversight "
        "(ceo/governance/auditor/data/platform); it is always added automatically.\n"
        "Catalog:\n" + lines
    )


def resolve_selection(keys: list[str]) -> list[dict]:
    """Turn a founder's picked keys into the specs to spin up (RFC 0002).

    Unknown keys are ignored, duplicates collapse, and the guaranteed oversight
    blocks are always appended — so whatever the founder selects, the company still
    launches with its CEO and oversight roles. Ordered (picked blocks first, then
    core) and deduped, ready for ``provision_fleet`` (which guarantees the required
    roles again as a backstop).
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for key in keys:
        fn = _BY_KEY.get(key)
        if fn is None or fn.core or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    for fn in core_functions():
        if fn.key not in seen:
            seen.add(fn.key)
            ordered.append(fn.key)
    return [spec_for(key) for key in ordered]


def picked_selectable(keys: list[str]) -> list[str]:
    """The recognized selectable keys among ``keys`` (drops unknown + oversight).

    Onboarding uses this to decide the function-first path: any selectable pick →
    provision from the catalog; none → fall back to the LLM org designer."""
    out: list[str] = []
    for key in keys:
        fn = _BY_KEY.get(key)
        if fn is not None and not fn.core and key not in out:
            out.append(key)
    return out
