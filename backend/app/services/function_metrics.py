"""Metric metadata for function health signals (RFC 0002).

One place that knows, for every KPI a function is judged on: its unit, whether
lower is better (``bounce_rate`` improves as it falls), and a sensible default
target to seed a `KeyResult` with. `function_health` seeds KRs from this,
`function_improvement` detects off-target against it, and `function_learning`
reads direction from here (one source, no drift).

Beyond the business KPIs, this adds **agent-based** signals — the operating health
of the agents themselves (reliability, trust, ROI), derived from the per-agent
reputation model. They're seeded as KRs on every company so a function's scorecard
covers not just business outcomes but whether the agent running it is dependable.
"""

from __future__ import annotations

#: name → (unit, lower_is_better, default_target). ``target`` is None when there's
#: no universal default (an absolute like MRR is company-specific — the founder/CEO
#: sets it later on the seeded KR).
SIGNAL_META: dict[str, tuple[str, bool, float | None]] = {
    # website
    "website_visitors": ("visitors/mo", False, 1000),
    "signup_conversion_rate": ("ratio", False, 0.05),
    "bounce_rate": ("ratio", True, 0.4),
    # social
    "social_followers": ("followers", False, 1000),
    "social_engagement_rate": ("ratio", False, 0.03),
    "social_reach": ("accounts/mo", False, 5000),
    # outbound
    "outbound_meetings_booked": ("meetings/mo", False, 10),
    "outbound_reply_rate": ("ratio", False, 0.1),
    "pipeline_created": ("USD", False, None),
    # inbound
    "inbound_leads": ("leads/mo", False, 50),
    "lead_qualification_rate": ("ratio", False, 0.3),
    "inbound_response_time": ("hours", True, 24),
    # brand
    "brand_consistency_score": ("score", False, 0.8),
    "creative_assets_delivered": ("assets/mo", False, 10),
    # customer service
    "csat": ("score", False, 0.9),
    "first_response_time": ("hours", True, 4),
    "churn_rate": ("ratio", True, 0.05),
    # engineering (RFC 0003)
    "code_tasks_shipped": ("tasks/mo", False, None),
    "ci_pass_rate": ("ratio", False, 0.9),
    "review_turnaround_hours": ("hours", True, 24),
    # legal
    "contracts_reviewed": ("contracts", False, None),
    "compliance_issues_open": ("issues", True, 0),
    # finance
    "runway_months": ("months", False, 12),
    "gross_margin": ("ratio", False, 0.5),
    "burn_rate": ("USD/mo", True, None),
    # billing
    "mrr": ("USD", False, None),
    "failed_payment_rate": ("ratio", True, 0.05),
    "collections_outstanding": ("USD", True, None),
    # agent-based (operating health of the agents themselves, from reputation)
    "agent_reliability": ("score", False, 0.8),
    "agent_trust": ("score", False, 0.8),
    "agent_roi": ("score", False, 0.55),
}

#: The agent-based KPIs, seeded as KRs on every company (RFC 0002) so a scorecard
#: covers whether the agents running the functions are dependable — not just the
#: business outcomes. Recorded from the reputation model by `function_health`.
AGENT_SIGNALS: tuple[str, ...] = ("agent_reliability", "agent_trust", "agent_roi")


def is_lower_better(name: str) -> bool:
    """Whether a *lower* value is the improvement for this metric (default: no)."""
    meta = SIGNAL_META.get(name)
    return bool(meta[1]) if meta else False


def signal_unit(name: str) -> str | None:
    meta = SIGNAL_META.get(name)
    return meta[0] if meta else None


def default_target(name: str) -> float | None:
    meta = SIGNAL_META.get(name)
    return meta[2] if meta else None
