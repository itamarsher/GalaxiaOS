"""Company Builder: mission → objectives/OKRs → agent fleet → launch.

The generation LLM calls go through the same :class:`CostMeter` as runtime work,
so even company generation respects the founder's budget.
"""

from __future__ import annotations

import json
import time
import uuid
from threading import Lock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import (
    Agent,
    AgentEdge,
    Budget,
    Company,
    InvestmentReview,
    KeyResult,
    Membership,
    Mission,
    Objective,
    Policy,
    User,
)
from app.models.enums import (
    AgentRole,
    AutonomyLevel,
    BudgetPeriod,
    CompanyStatus,
    EdgeRelation,
    MembershipRole,
    PolicyEffect,
    PolicyScope,
)
from app.observability import get_logger
from app.providers.base import LLMResponse, Message
from app.runtime import orchestrator
from app.runtime.cost_meter import CostMeter
from app.runtime.prompts import (
    MISSION_TO_PLAN_SCHEMA,
    MISSION_TO_PLAN_SYSTEM,
    PLAN_TO_ORG_SCHEMA,
    PLAN_TO_ORG_SYSTEM,
    REFINE_SCHEMA,
    REFINE_SYSTEM,
    generation_language_directive,
)
from app.services import apikeys, data_policy, investors, worker_binding
from app.services import chat as chat_svc
from app.services import governance as gov

_log = get_logger("abos.onboarding")


class OnboardingError(Exception):
    pass


# ── Generation progress telemetry ─────────────────────────────────────────────
# Organization generation runs two sequential LLM calls and an investor review,
# so it is far from instant. The handler updates this in-process registry as it
# moves through phases; ``GET /onboarding/{id}/generate/status`` reads it
# concurrently (the generate request is still in flight) so the founder sees a
# live spinner with real progress instead of a frozen button. Single-instance
# scope is sufficient for onboarding; if a multi-worker deploy ever splits the
# two requests across processes, the status simply reads "running" until the
# generate POST returns the finished preview.
_PROGRESS: dict[str, dict] = {}
_PROGRESS_LOCK = Lock()
_MAX_EVENTS = 40
# Cap how many companies' progress blobs we retain. Each finished generation
# otherwise leaves its blob (up to ``_MAX_EVENTS`` events) in memory forever —
# a slow leak over the life of the process. We evict the least-recently-updated
# entries once the registry grows past this, which is harmless: a stale blob is
# only read by the founder's spinner while a generate request is still in flight.
_MAX_TRACKED_COMPANIES = 256


def _evict_stale_progress_locked(keep_key: str) -> None:
    """Bound ``_PROGRESS`` to the most recent companies. Caller holds the lock."""
    if len(_PROGRESS) <= _MAX_TRACKED_COMPANIES:
        return
    victims = sorted(
        (k for k in _PROGRESS if k != keep_key),
        key=lambda k: _PROGRESS[k].get("updated_at", 0.0),
    )
    for k in victims[: len(_PROGRESS) - _MAX_TRACKED_COMPANIES]:
        del _PROGRESS[k]


def reset_progress(company_id: uuid.UUID) -> None:
    with _PROGRESS_LOCK:
        _evict_stale_progress_locked(str(company_id))
        _PROGRESS[str(company_id)] = {
            "phase": "queued",
            "pct": 0,
            "message": "Starting…",
            "status": "running",
            "error": None,
            "events": [],
            "updated_at": time.time(),
        }


def set_progress(
    company_id: uuid.UUID,
    *,
    phase: str,
    pct: int,
    message: str,
    status: str = "running",
    error: str | None = None,
) -> None:
    key = str(company_id)
    with _PROGRESS_LOCK:
        prev = _PROGRESS.get(key) or {}
        events = list(prev.get("events", []))
        events.append({"ts": time.time(), "label": message, "pct": pct})
        del events[:-_MAX_EVENTS]
        _PROGRESS[key] = {
            "phase": phase,
            "pct": pct,
            "message": message,
            "status": status,
            "error": error,
            "events": events,
            "updated_at": time.time(),
        }


def get_progress(company_id: uuid.UUID) -> dict | None:
    with _PROGRESS_LOCK:
        state = _PROGRESS.get(str(company_id))
        return dict(state) if state else None


def _extract_json_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` span in *text*, or ``None``.

    Naive ``find("{")``/``rfind("}")`` slicing breaks when the model wraps the
    JSON in prose, emits more than one object, or gets truncated mid-output: the
    outermost braces no longer delimit a valid object. Here we walk the text and
    track brace depth (ignoring braces inside strings) to pull out the first
    complete object.
    """
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    return text[start : i + 1]
    return None


# Stop reasons the providers report when generation hit the token ceiling
# (Anthropic: "max_tokens"; OpenAI: "length"). When this happens the JSON is
# almost certainly cut off mid-object, so we surface a specific error rather
# than a generic "malformed JSON" — the founder can't fix a truncation.
_TRUNCATED_STOP_REASONS = {"max_tokens", "length"}


def _parse_llm_json(resp: LLMResponse) -> dict:
    """Parse the JSON body of an onboarding LLM response.

    Distinguishes the three failure modes a founder can actually hit:
    a truncated response (token limit), no JSON at all, and balanced-but-invalid
    JSON — each gets a handled :class:`OnboardingError` (400) instead of an
    unhandled decode error bubbling up as a 500.
    """
    if resp.stop_reason in _TRUNCATED_STOP_REASONS:
        _log.warning("LLM response truncated (stop_reason=%s)", resp.stop_reason)
        raise OnboardingError(
            "The model's response was cut off before it finished. Please try "
            "generating again."
        )

    text = resp.text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        text = text.lstrip("json").strip().strip("`")
    candidate = _extract_json_object(text)
    if candidate is None:
        raise OnboardingError("LLM did not return JSON")
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        # Generation forces structured JSON at the provider, so this should be
        # rare; log enough to diagnose if a provider ever returns junk anyway.
        _log.warning(
            "failed to parse LLM JSON response (model=%s, stop_reason=%s): %s | raw=%r",
            resp.model,
            resp.stop_reason,
            exc,
            text[:2000],
        )
        raise OnboardingError("LLM returned malformed JSON; please try again.") from exc


def _as_dicts(items: object, key: str) -> list[dict]:
    """Normalize an LLM list into dicts, tolerating bare strings.

    JSON mode guarantees valid JSON but not the schema, so a list element may
    arrive as a plain string (e.g. ``"ceo"``) instead of an object. Coerce
    strings to ``{key: value}`` and drop anything that isn't a string or dict —
    a wrong shape should never crash persistence.
    """
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for item in items:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, str):
            out.append({key: item})
    return out


def _as_int(value: object, default: int | None) -> int | None:
    """Coerce a possibly-stringy numeric field to ``int``; fall back on failure."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _clean_company_name(name: object, fallback: str) -> str:
    """Trim a model-provided company name to brand-name length.

    ``name`` is expected to be a short brand-style string, but a misbehaving
    model could still hand back a full sentence — strip trailing punctuation
    and cap well below the ``Company.name`` column limit so a stray long
    string never re-creates the mission-as-name bug.
    """
    cleaned = str(name or "").strip().rstrip(".!?,;:").strip()
    if not cleaned:
        return fallback
    return cleaned[:80]


# A sensible default fleet, used to backfill whatever the org-design LLM omits so
# the company is never left without a working org (it must at least have a CEO to
# plan/dispatch and a Governance agent to oversee).
_DEFAULT_FLEET: list[dict] = [
    {
        "role": "ceo",
        "name": "CEO",
        "responsibility": "Own strategy: decompose the mission into initiatives and dispatch them to the team.",
        "autonomy_level": "approve_required",
    },
    {
        "role": "growth",
        "name": "Growth Lead",
        "responsibility": "Own customer acquisition and demand generation.",
        "autonomy_level": "approve_required",
    },
    {
        "role": "research",
        "name": "Research Lead",
        "responsibility": "Own market and competitive intelligence.",
        "autonomy_level": "approve_required",
    },
    {
        "role": "product",
        "name": "Product Lead",
        "responsibility": "Own product planning and roadmap.",
        "autonomy_level": "approve_required",
    },
    {
        "role": "design",
        "name": "Graphic Designer",
        "responsibility": (
            "Own the company's visual identity and brand creative. Generate on-brand "
            "photos and short videos with Google's Nano Banana, keep the brand & design "
            "guidelines current, and deliver imagery for marketing, social, and the product."
        ),
        "autonomy_level": "approve_required",
    },
    {
        "role": "finance",
        "name": "Finance Lead",
        "responsibility": "Own budget monitoring and unit economics.",
        "autonomy_level": "approve_required",
    },
    {
        "role": "auditor",
        "name": "Auditor",
        "responsibility": "Keep the financial records audited and the invoice/receipt paper trail accurate.",
        "autonomy_level": "approve_required",
    },
    {
        "role": "governance",
        "name": "Governance Lead",
        "responsibility": "Own safety, compliance, and oversight.",
        "autonomy_level": "approve_required",
    },
    {
        "role": "data",
        "name": "Data Lead",
        "responsibility": (
            "Own the company's data: make sure every internal agent can reach the data it "
            "needs, and control what data is shared with anyone outside the company."
        ),
        "autonomy_level": "approve_required",
    },
    {
        "role": "platform",
        "name": "Platform Engineer",
        "responsibility": (
            "Stay dormant until another agent reports a bug or requests a capability; then "
            "turn it into a precise tracker issue — investigating the code for bugs, and "
            "capturing the business case and product requirement (not the implementation) "
            "for capability requests — so the platform can be fixed or extended."
        ),
        "autonomy_level": "approve_required",
    },
]


def _fleet_specs(parsed: list[dict]) -> list[dict]:
    """Return the agent specs to build, backfilling a usable fleet.

    The org-design LLM can return an empty or partial ``agents`` list (the JSON
    schema permits it). Rather than ship an empty org, fall back to the default
    fleet when nothing usable came back, and always guarantee a CEO + Governance.
    """
    specs = [s for s in parsed if s.get("role")]
    if not specs:
        return [dict(s) for s in _DEFAULT_FLEET]
    roles = {str(s.get("role")) for s in specs}
    defaults = {s["role"]: s for s in _DEFAULT_FLEET}
    if "ceo" not in roles:
        specs.insert(0, dict(defaults["ceo"]))
    # Must-have oversight roles: governance, the financial auditor, the data
    # agent (data access for internal agents + control over external sharing),
    # and the platform agent (dormant escalation target for bug/feature reports).
    for required in ("auditor", "governance", "data", "platform"):
        if required not in roles:
            specs.append(dict(defaults[required]))
    return specs


# Relative share of the monthly budget by role. Coordination/oversight roles
# (Governance) carry a smaller operational share than the functional agents
# that actually spend on the world (Growth runs the most spend-heavy work:
# acquisition, outreach, ads). Tunable — only the ratios matter. The CEO is not
# listed here: it is never given a per-agent cap (limited only by the global
# company budget), so it is excluded from the weighted split.
_DEFAULT_BUDGET_WEIGHT = 2.0
_ROLE_BUDGET_WEIGHTS: dict[AgentRole, float] = {
    AgentRole.governance: 1.0,
    AgentRole.auditor: 1.0,
    # The platform agent is idle most of the time (only wakes when triggered), so
    # it carries the smallest operational share.
    AgentRole.platform: 1.0,
    AgentRole.data: 1.5,
    AgentRole.finance: 1.5,
    AgentRole.research: 2.0,
    AgentRole.product: 2.0,
    # The designer runs paid image/video generation, so it carries a functional share.
    AgentRole.design: 2.0,
    AgentRole.growth: 3.0,
    AgentRole.custom: 2.0,
}


def _weighted_split(weights: list[float], total_cents: int | None) -> list[int | None]:
    """Split ``total_cents`` across items proportional to ``weights``.

    Uses the largest-remainder method so the integer parts sum to exactly
    ``total_cents`` (no cents lost to rounding).
    """
    n = len(weights)
    if n == 0:
        return []
    if not total_cents or total_cents <= 0:
        return [None] * n
    wsum = sum(weights)
    if wsum <= 0:  # degenerate — fall back to an even split
        weights = [1.0] * n
        wsum = float(n)
    raw = [total_cents * w / wsum for w in weights]
    parts = [int(x) for x in raw]
    remainder = int(total_cents) - sum(parts)
    # Hand the leftover cents to the largest fractional remainders, biggest first.
    for i in sorted(range(n), key=lambda i: raw[i] - parts[i], reverse=True)[:remainder]:
        parts[i] += 1
    return parts


async def _reallocate_agent_budgets(
    db: AsyncSession, *, company_id: uuid.UUID, total_cents: int | None
) -> None:
    """Re-split the company's monthly budget across agents, weighted by role.

    Start lean: only ``1 - launch_budget_reserve_fraction`` of the budget is
    split across the fleet; the remainder stays unallocated as the CEO's pool, so
    the team doesn't commit the whole budget up front and the CEO has reserve to
    deploy later via approved hires.

    The CEO is deliberately left uncapped (``monthly_budget_cents = None``): it
    owns the whole company budget and is limited only by the global ceiling, so
    it can deploy the reserve pool without hitting a personal per-agent cap.
    """
    agents = (
        await db.scalars(
            select(Agent)
            .where(Agent.company_id == company_id)
            .order_by(Agent.created_at.asc(), Agent.id.asc())
        )
    ).all()
    allocatable = total_cents
    if total_cents and total_cents > 0:
        reserve = min(max(settings.launch_budget_reserve_fraction, 0.0), 1.0)
        allocatable = int(total_cents * (1.0 - reserve))
    # The CEO is limited only by the global company budget, not a per-agent slice.
    capped = [a for a in agents if a.role != AgentRole.ceo]
    for agent in agents:
        if agent.role == AgentRole.ceo:
            agent.monthly_budget_cents = None
    weights = [_ROLE_BUDGET_WEIGHTS.get(a.role, _DEFAULT_BUDGET_WEIGHT) for a in capped]
    shares = _weighted_split(weights, allocatable)
    shares = _apply_min_floor(shares, total_cents)
    for agent, cents in zip(capped, shares, strict=True):
        agent.monthly_budget_cents = cents
    await db.flush()


def _apply_min_floor(
    shares: list[int | None], total_cents: int | None
) -> list[int | None]:
    """Raise each agent slice to at least ``launch_agent_min_budget_cents``.

    The lean weighted split can leave an agent with only a few cents — too little
    to take one metered step — which makes routine work trip BudgetExceeded. Lift
    every slice to the floor (drawing the extra from the CEO reserve pool), but if
    the fleet's combined floors wouldn't fit the whole company budget, scale the
    slices down proportionally so the caps never over-commit the ceiling.
    """
    floor = max(0, settings.launch_agent_min_budget_cents)
    if not total_cents or total_cents <= 0 or floor == 0 or not shares:
        return shares
    floored = [c if c is None else max(c, floor) for c in shares]
    committed = sum(c for c in floored if c)
    if committed > total_cents:
        scale = total_cents / committed
        floored = [c if c is None else max(1, int(c * scale)) for c in floored]
    return floored


async def provision_fleet(
    db: AsyncSession,
    *,
    company: Company,
    specs: list[dict],
    total_budget_cents: int | None,
) -> dict[str, uuid.UUID]:
    """Persist an agent fleet, wire it under a single CEO, and split the budget.

    Shared by LLM generation and the deterministic Galaxia bootstrap so both
    produce an identically-wired org chart — functional agents reporting to the
    CEO, with the monthly budget allocated by role. ``specs`` is the already-
    resolved fleet; run it through :func:`_fleet_specs` first to guarantee the
    oversight roles (incl. the platform agent). Returns a ``role -> agent_id`` map.
    """
    # Idempotent by role: a non-``custom`` role the company already has is reused
    # rather than duplicated, so calling this on a non-empty fleet can never create
    # a second CEO (or governance/auditor/etc.). ``custom`` agents are always added.
    existing: dict[str, Agent] = {}
    for a in (
        await db.scalars(select(Agent).where(Agent.company_id == company.id))
    ).all():
        if a.role is not AgentRole.custom:
            existing.setdefault(a.role.value, a)

    role_to_agent: dict[str, uuid.UUID] = {}
    for spec in specs:
        try:
            role = AgentRole(spec.get("role", "custom"))
        except ValueError:
            role = AgentRole.custom
        if role is not AgentRole.custom and role.value in existing:
            role_to_agent[role.value] = existing[role.value].id
            continue
        agent = Agent(
            company_id=company.id,
            role=role,
            name=str(spec.get("name") or role.value.title())[:255],
            system_prompt=str(spec.get("responsibility") or ""),
            autonomy_level=_parse_autonomy(spec.get("autonomy_level")),
            access_labels=data_policy.default_access_labels_for_role(role.value),
            backend_type=worker_binding.default_backend_for(role),
        )
        db.add(agent)
        await db.flush()
        role_to_agent[role.value] = agent.id
        if role is not AgentRole.custom:
            existing[role.value] = agent

    # Wire functional agents under the CEO.
    ceo_id = role_to_agent.get("ceo")
    if ceo_id:
        for role_name, agent_id in role_to_agent.items():
            if role_name == "ceo":
                continue
            await db.execute(
                Agent.__table__.update()
                .where(Agent.id == agent_id)
                .values(reports_to_agent_id=ceo_id)
            )
            db.add(
                AgentEdge(
                    company_id=company.id,
                    from_agent_id=agent_id,
                    to_agent_id=ceo_id,
                    relation=EdgeRelation.reports_to,
                )
            )

    await db.flush()
    await _reallocate_agent_budgets(
        db, company_id=company.id, total_cents=total_budget_cents
    )
    return role_to_agent


async def start(
    db: AsyncSession,
    *,
    user: User,
    mission_text: str,
    budget_cents: int,
    constraints: list[str] | None,
    involvement: str | None = None,
) -> Company:
    """Create the draft company, budget, and mission. No LLM call yet.

    Every company is an ordinary tenant; there is no special "first company" — the
    operator (dogfooding) company, if any, is named explicitly via
    ``ABOS_PLATFORM_COMPANY_ID`` (services/platform_company.py).
    """
    company = Company(owner_user_id=user.id, name="Untitled Company", status=CompanyStatus.draft)
    db.add(company)
    await db.flush()

    db.add(
        Membership(
            user_id=user.id,
            company_id=company.id,
            role=MembershipRole.founder,
            # The founder's own stated involvement (how they want to be looped in).
            involvement=(involvement or "").strip() or None,
        )
    )
    db.add(
        Budget(
            company_id=company.id,
            period=BudgetPeriod.monthly,
            limit_cents=budget_cents,
        )
    )
    mission = Mission(
        company_id=company.id, raw_text=mission_text, constraints=constraints or []
    )
    db.add(mission)
    await db.flush()
    company.mission_id = mission.id
    await db.flush()
    return company


async def generate(db: AsyncSession, *, company: Company) -> dict:
    """Run the generation LLM calls and persist objectives, KRs, agents, edges."""
    resolved = await apikeys.resolve_active_provider(db, company_id=company.id)
    if resolved is None:
        raise OnboardingError(
            "No model available to generate the organization. Add your own provider API key, "
            "or (managed mode) the free platform allowance is used up — upgrade or bring a key."
        )
    provider, api_key = resolved.provider, resolved.api_key
    funding_user_id = resolved.funding_user_id
    planner_model = provider.default_models["planner"]
    # Use the model's full output ceiling so generation is never truncated; the
    # provider streams internally above its safe non-streaming size.
    gen_max_tokens = provider.max_output_tokens(planner_model)

    mission = await db.scalar(select(Mission).where(Mission.company_id == company.id))
    budget = await db.scalar(select(Budget).where(Budget.company_id == company.id))

    # Abuse backstop: a mission the PLATFORM is funding (managed free/paid tier)
    # passes a cheap acceptability screen first. A founder on their own key is
    # exempt — their provider's own policies govern what they can run.
    if resolved.source == "platform":
        from app.services.screening import screen_mission

        ok, reason = screen_mission(mission.raw_text if mission else "")
        if not ok:
            raise OnboardingError(reason or "This mission can't run on the free platform tier.")

    meter = CostMeter(SessionLocal)
    set_progress(
        company.id, phase="planning", pct=10, message="Processing…"
    )

    # ── LLM #1: mission → plan ────────────────────────────────────────────────
    plan_resp = await meter.run_llm(
        provider,
        api_key=api_key,
        company_id=company.id,
        agent_id=None,
        task_id=None,
        model=planner_model,
        system=MISSION_TO_PLAN_SYSTEM,
        messages=[Message(role="user", content=mission.raw_text)],
        max_tokens=gen_max_tokens,
        json_schema=MISSION_TO_PLAN_SCHEMA,
        funding_user_id=funding_user_id,
    )
    plan = _parse_llm_json(plan_resp)
    set_progress(
        company.id,
        phase="objectives",
        pct=40,
        message="Drafting objectives and key results",
    )

    mission.generated_summary = plan.get("summary")
    mission.business_model_assumptions = plan.get("business_model_assumptions")
    mission.target_market = plan.get("target_market")
    company.name = _clean_company_name(plan.get("name"), company.name)

    # Language detected once here (from the raw mission — the strongest signal) and
    # reused by every later stage so the whole company speaks the founder's language
    # deterministically, instead of each stage re-detecting from derived text.
    language = str(plan.get("language") or "").strip()[:20] or None
    mission.language = language

    for i, obj in enumerate(_as_dicts(plan.get("objectives"), "title")):
        objective = Objective(
            company_id=company.id,
            mission_id=mission.id,
            title=str(obj.get("title") or f"Objective {i+1}")[:500],
            rationale=obj.get("rationale"),
            priority=_as_int(obj.get("priority"), i + 1),
        )
        db.add(objective)
        await db.flush()
        for kr in _as_dicts(obj.get("key_results"), "metric"):
            db.add(
                KeyResult(
                    company_id=company.id,
                    objective_id=objective.id,
                    metric=str(kr.get("metric") or "metric")[:255],
                    target_value=kr.get("target_value"),
                    unit=kr.get("unit"),
                )
            )

    # ── LLM #2: plan + budget → org design ────────────────────────────────────
    set_progress(
        company.id, phase="org", pct=55, message="Designing the agent fleet"
    )
    # Carry the raw mission (not just the derived objectives) so the org designer
    # reasons in the founder's own words and locale; ensure_ascii=False keeps
    # non-Latin scripts intact instead of escaping them to \\uXXXX gibberish.
    org_input = json.dumps(
        {
            "mission": mission.raw_text,
            "objectives": plan.get("objectives", []),
            "monthly_budget_cents": budget.limit_cents,
        },
        ensure_ascii=False,
    )
    org_resp = await meter.run_llm(
        provider,
        api_key=api_key,
        company_id=company.id,
        agent_id=None,
        task_id=None,
        model=planner_model,
        system=PLAN_TO_ORG_SYSTEM + generation_language_directive(language),
        messages=[Message(role="user", content=org_input)],
        max_tokens=gen_max_tokens,
        json_schema=PLAN_TO_ORG_SCHEMA,
        funding_user_id=funding_user_id,
    )
    org = _parse_llm_json(org_resp)
    set_progress(
        company.id, phase="wiring", pct=80, message="Wiring the org chart"
    )

    # Ignore any per-agent budget figures the LLM guessed — provision_fleet owns
    # the allocation so it always sums correctly.
    role_to_agent = await provision_fleet(
        db,
        company=company,
        specs=_fleet_specs(_as_dicts(org.get("agents"), "role")),
        total_budget_cents=budget.limit_cents,
    )

    # ── Investment review (best-effort; never breaks generation) ──────────────
    investor_reviews = 0
    if settings.investor_review_enabled:
        set_progress(
            company.id, phase="review", pct=90, message="Running the investor review"
        )
        try:
            reviews = await investors.review(db, company=company)
            investor_reviews = len(reviews)
        except Exception:  # noqa: BLE001 - a review failure must not fail generation
            _log.exception("investment review failed for company %s", company.id)

    return {
        "cost_estimate_cents": _as_int(org.get("monthly_cost_estimate_cents"), None),
        "agent_roles": list(role_to_agent.keys()),
        "investor_reviews": investor_reviews,
    }


def _parse_autonomy(value: str | None) -> AutonomyLevel:
    try:
        return AutonomyLevel(value)
    except (ValueError, TypeError):
        return AutonomyLevel.approve_required


async def _current_plan_snapshot(db: AsyncSession, company: Company) -> dict:
    """Serialize the current objectives + agent fleet for the refine prompt."""
    objectives = (
        await db.scalars(
            select(Objective)
            .where(Objective.company_id == company.id)
            .order_by(Objective.priority)
        )
    ).all()
    obj_payload = []
    for o in objectives:
        krs = (
            await db.scalars(select(KeyResult).where(KeyResult.objective_id == o.id))
        ).all()
        obj_payload.append(
            {
                "title": o.title,
                "rationale": o.rationale,
                "priority": o.priority,
                "key_results": [
                    {"metric": k.metric, "target_value": k.target_value, "unit": k.unit}
                    for k in krs
                ],
            }
        )
    agents = (
        await db.scalars(select(Agent).where(Agent.company_id == company.id))
    ).all()
    agent_payload = [
        {
            "role": a.role.value,
            "name": a.name,
            "responsibility": a.system_prompt,
            "autonomy_level": a.autonomy_level.value,
            "monthly_budget_cents": a.monthly_budget_cents,
        }
        for a in agents
    ]
    return {"company_name": company.name, "objectives": obj_payload, "agents": agent_payload}


async def _investor_reviews_context(db: AsyncSession, company: Company) -> str:
    """The investor verdicts as compact JSON, so the founder can discuss them with
    the AI while refining the plan. Empty string when no review has been run."""
    reviews = (
        await db.scalars(
            select(InvestmentReview)
            .where(InvestmentReview.company_id == company.id)
            .order_by(InvestmentReview.created_at)
        )
    ).all()
    if not reviews:
        return ""
    payload = [
        {
            "persona": r.persona.value,
            "stance": r.stance.value,
            "conviction": r.conviction,
            "headline": r.headline,
            "thesis": r.thesis,
            "strengths": r.strengths,
            "risks": r.risks,
            "conditions": r.conditions,
        }
        for r in reviews
    ]
    return json.dumps(payload)


async def refine(db: AsyncSession, *, company: Company, message: str) -> dict:
    """Conversationally edit a draft company's objectives / agent fleet.

    Returns ``{"reply": str}``. The LLM emits a structured patch (validated
    against an allow-list of fields) that *code* applies — objectives are
    replaced wholesale; agents are upserted by role and may be removed (never the
    CEO). The company budget can be changed too, and any change to the budget or
    the fleet size re-splits the budget evenly across the agents.
    """
    if company.status is not CompanyStatus.draft:
        return {"reply": "This company has already launched, so its plan is now live and can't be edited here."}

    resolved = await apikeys.resolve_active_provider(db, company_id=company.id)
    if resolved is None:
        return {
            "reply": "No model available to refine the plan — add your own provider key, or "
            "(managed mode) the free platform allowance is used up; upgrade or bring a key."
        }
    provider, api_key = resolved.provider, resolved.api_key
    funding_user_id = resolved.funding_user_id
    planner_model = provider.default_models["planner"]

    snapshot = await _current_plan_snapshot(db, company)
    reviews_ctx = await _investor_reviews_context(db, company)
    language = await db.scalar(
        select(Mission.language).where(Mission.company_id == company.id)
    )
    meter = CostMeter(SessionLocal)
    resp = await meter.run_llm(
        provider,
        api_key=api_key,
        company_id=company.id,
        agent_id=None,
        task_id=None,
        model=planner_model,
        system=REFINE_SYSTEM + generation_language_directive(language),
        messages=[
            Message(
                role="user",
                content=(
                    f"Current plan:\n{json.dumps(snapshot, ensure_ascii=False)}\n\n"
                    + (
                        f"Investor reviews of this plan:\n{reviews_ctx}\n\n"
                        if reviews_ctx
                        else ""
                    )
                    + f"Founder instruction: {message}"
                ),
            )
        ],
        max_tokens=provider.max_output_tokens(planner_model),
        json_schema=REFINE_SCHEMA,
        funding_user_id=funding_user_id,
    )
    try:
        patch = _parse_llm_json(resp)
    except OnboardingError:
        return {"reply": "I couldn't process that change — please rephrase and try again."}

    mission = await db.scalar(select(Mission).where(Mission.company_id == company.id))
    budget = await db.scalar(select(Budget).where(Budget.company_id == company.id))
    budget_changed = False
    fleet_changed = False

    new_name = patch.get("company_name")
    if isinstance(new_name, str) and new_name.strip():
        company.name = new_name.strip()[:120]

    new_budget = _as_int(patch.get("monthly_budget_cents"), None)
    if new_budget and new_budget > 0 and budget is not None and budget.limit_cents != new_budget:
        budget.limit_cents = new_budget
        budget_changed = True

    new_objectives = _as_dicts(patch.get("objectives"), "title")
    if new_objectives and mission is not None:
        # Replace the objective tree wholesale (KRs cascade on delete).
        existing = (
            await db.scalars(select(Objective).where(Objective.company_id == company.id))
        ).all()
        for o in existing:
            await db.delete(o)
        await db.flush()
        for i, obj in enumerate(new_objectives):
            objective = Objective(
                company_id=company.id,
                mission_id=mission.id,
                title=str(obj.get("title") or f"Objective {i+1}")[:500],
                rationale=obj.get("rationale"),
                priority=_as_int(obj.get("priority"), i + 1),
            )
            db.add(objective)
            await db.flush()
            for kr in _as_dicts(obj.get("key_results"), "metric"):
                db.add(
                    KeyResult(
                        company_id=company.id,
                        objective_id=objective.id,
                        metric=str(kr.get("metric") or "metric")[:255],
                        target_value=kr.get("target_value"),
                        unit=kr.get("unit"),
                    )
                )

    by_role = {
        a.role.value: a
        for a in (
            await db.scalars(select(Agent).where(Agent.company_id == company.id))
        ).all()
    }

    # Remove agents the founder asked to drop (never the CEO).
    for role_name in patch.get("remove_roles") or []:
        if not isinstance(role_name, str):
            continue
        agent = by_role.get(role_name)
        if agent is not None and agent.role is not AgentRole.ceo:
            await db.delete(agent)
            by_role.pop(role_name, None)
            fleet_changed = True
    if fleet_changed:
        await db.flush()

    new_agents = _as_dicts(patch.get("agents"), "role")
    if new_agents:
        ceo = by_role.get(AgentRole.ceo.value)
        for spec in new_agents:
            try:
                role = AgentRole(spec.get("role", "custom"))
            except ValueError:
                role = AgentRole.custom
            agent = by_role.get(role.value)
            if agent is None:
                # Add a new functional agent, wired under the CEO. Per-agent
                # budget is set by the reallocation step below, not here.
                agent = Agent(
                    company_id=company.id,
                    role=role,
                    name=str(spec.get("name") or role.value.title())[:255],
                    system_prompt=str(spec.get("responsibility") or ""),
                    autonomy_level=_parse_autonomy(spec.get("autonomy_level")),
                    access_labels=data_policy.default_access_labels_for_role(role.value),
                    backend_type=worker_binding.default_backend_for(role),
                    reports_to_agent_id=ceo.id if (ceo and role is not AgentRole.ceo) else None,
                )
                db.add(agent)
                await db.flush()
                by_role[role.value] = agent
                fleet_changed = True
                if ceo and role is not AgentRole.ceo:
                    db.add(
                        AgentEdge(
                            company_id=company.id,
                            from_agent_id=agent.id,
                            to_agent_id=ceo.id,
                            relation=EdgeRelation.reports_to,
                        )
                    )
            else:
                if spec.get("name"):
                    agent.name = str(spec["name"])[:255]
                if spec.get("responsibility"):
                    agent.system_prompt = str(spec["responsibility"])
                if spec.get("autonomy_level"):
                    agent.autonomy_level = _parse_autonomy(spec.get("autonomy_level"))
        await db.flush()

    # Reallocate the monthly budget across the fleet whenever the budget or the
    # number of agents changed (the two things that should move the split).
    if budget_changed or fleet_changed:
        await _reallocate_agent_budgets(
            db, company_id=company.id, total_cents=budget.limit_cents if budget else None
        )

    reply = patch.get("reply")
    return {
        "reply": str(reply) if reply else "Done — I've updated the plan.",
        "cost_estimate_cents": _as_int(patch.get("monthly_cost_estimate_cents"), None),
    }


async def launch(db: AsyncSession, *, company: Company) -> uuid.UUID | None:
    """Seed governance, activate the company, and create the root CEO run.

    A company can't operate without a file store — agents file every report and
    artifact there — so launch requires a connected storage provider (Google
    Drive), for an AI operator driving onboarding over the Founder MCP just as for
    a human founder. The check only bites where storage *can* be connected (the
    Drive OAuth app is configured); deployments/tests without it skip the guard so
    the requirement never becomes an un-satisfiable dead end.
    """
    if settings.require_storage_to_launch:
        from app.integrations import gdrive_oauth
        from app.services.integrations import resolve_file_provider

        if gdrive_oauth.connect_configured() and (
            await resolve_file_provider(db, company_id=company.id) is None
        ):
            raise OnboardingError(
                "Connect a storage provider before launching: this company has no file "
                "store, and its agents can't persist reports, artifacts, or saved "
                "documents without one. Connect Google Drive (Settings → Integrations, "
                "or the account-wide grant at /auth/google/drive/connect), then launch."
            )

    for spec in gov.default_policies():
        db.add(
            Policy(
                company_id=company.id,
                name=spec["name"],
                scope=PolicyScope(spec["scope"]),
                rule=spec["rule"],
                effect=PolicyEffect(spec["effect"]),
                priority=spec["priority"],
            )
        )
    # Seed the "every external communication needs founder approval" guardrail
    # disabled, so it's visible and one toggle away (Communications settings) for
    # founders who want to vet all outbound messaging during early cycles.
    await gov.set_external_comms_approval(db, company_id=company.id, enabled=False)

    # Seed the data-segmentation taxonomy so the founder's labels exist from launch
    # (agents were provisioned with role-based access to these keys).
    await data_policy.seed_default_labels(db, company_id=company.id)

    company.status = CompanyStatus.active
    # Open the founder's standing direct line to the CEO up front, so it's there
    # to message the moment the company is live.
    await chat_svc.ensure_ceo_dm(db, company_id=company.id)
    task_id = await orchestrator.create_launch_run(db, company.id)
    await db.flush()
    return task_id
