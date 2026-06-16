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
)
from app.services import apikeys, investors
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


def reset_progress(company_id: uuid.UUID) -> None:
    with _PROGRESS_LOCK:
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


async def start(
    db: AsyncSession,
    *,
    user: User,
    mission_text: str,
    budget_cents: int,
    constraints: list[str] | None,
) -> Company:
    """Create the draft company, budget, and mission. No LLM call yet."""
    company = Company(owner_user_id=user.id, name="Untitled Company", status=CompanyStatus.draft)
    db.add(company)
    await db.flush()

    db.add(Membership(user_id=user.id, company_id=company.id, role=MembershipRole.founder))
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
    resolved = await apikeys.resolve_provider(db, company_id=company.id)
    if resolved is None:
        raise OnboardingError("Add a provider API key before generating the organization.")
    provider, api_key = resolved
    planner_model = provider.default_models["planner"]
    # Use the model's full output ceiling so generation is never truncated; the
    # provider streams internally above its safe non-streaming size.
    gen_max_tokens = provider.max_output_tokens(planner_model)

    mission = await db.scalar(select(Mission).where(Mission.company_id == company.id))
    budget = await db.scalar(select(Budget).where(Budget.company_id == company.id))
    meter = CostMeter(SessionLocal)
    set_progress(
        company.id, phase="planning", pct=10, message="Reading your mission and budget"
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
    company.name = str(plan.get("summary") or company.name)[:120]

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
    org_input = json.dumps(
        {
            "objectives": plan.get("objectives", []),
            "monthly_budget_cents": budget.limit_cents,
        }
    )
    org_resp = await meter.run_llm(
        provider,
        api_key=api_key,
        company_id=company.id,
        agent_id=None,
        task_id=None,
        model=planner_model,
        system=PLAN_TO_ORG_SYSTEM,
        messages=[Message(role="user", content=org_input)],
        max_tokens=gen_max_tokens,
        json_schema=PLAN_TO_ORG_SCHEMA,
    )
    org = _parse_llm_json(org_resp)
    set_progress(
        company.id, phase="wiring", pct=80, message="Wiring the org chart"
    )

    role_to_agent: dict[str, uuid.UUID] = {}
    for spec in _as_dicts(org.get("agents"), "role"):
        try:
            role = AgentRole(spec.get("role", "custom"))
        except ValueError:
            role = AgentRole.custom
        agent = Agent(
            company_id=company.id,
            role=role,
            name=str(spec.get("name") or role.value.title())[:255],
            system_prompt=str(spec.get("responsibility") or ""),
            autonomy_level=_parse_autonomy(spec.get("autonomy_level")),
            monthly_budget_cents=_as_int(spec.get("monthly_budget_cents"), None),
        )
        db.add(agent)
        await db.flush()
        role_to_agent[role.value] = agent.id

    # Wire functional agents under the CEO.
    ceo_id = role_to_agent.get("ceo")
    if ceo_id:
        for role, agent_id in role_to_agent.items():
            if role == "ceo":
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


async def refine(db: AsyncSession, *, company: Company, message: str) -> dict:
    """Conversationally edit a draft company's objectives / agent fleet.

    Returns ``{"reply": str}``. The LLM emits a structured patch (validated
    against an allow-list of fields) that *code* applies — objectives are
    replaced wholesale, agents are upserted by role. Never deletes agents, so
    the CEO and the org wiring stay intact.
    """
    if company.status is not CompanyStatus.draft:
        return {"reply": "This company has already launched, so its plan is now live and can't be edited here."}

    resolved = await apikeys.resolve_provider(db, company_id=company.id)
    if resolved is None:
        return {"reply": "Add a provider API key first, then I can refine the plan."}
    provider, api_key = resolved
    planner_model = provider.default_models["planner"]

    snapshot = await _current_plan_snapshot(db, company)
    meter = CostMeter(SessionLocal)
    resp = await meter.run_llm(
        provider,
        api_key=api_key,
        company_id=company.id,
        agent_id=None,
        task_id=None,
        model=planner_model,
        system=REFINE_SYSTEM,
        messages=[
            Message(
                role="user",
                content=(
                    f"Current plan:\n{json.dumps(snapshot)}\n\n"
                    f"Founder instruction: {message}"
                ),
            )
        ],
        max_tokens=provider.max_output_tokens(planner_model),
        json_schema=REFINE_SCHEMA,
    )
    try:
        patch = _parse_llm_json(resp)
    except OnboardingError:
        return {"reply": "I couldn't process that change — please rephrase and try again."}

    mission = await db.scalar(select(Mission).where(Mission.company_id == company.id))

    new_name = patch.get("company_name")
    if isinstance(new_name, str) and new_name.strip():
        company.name = new_name.strip()[:120]

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

    new_agents = _as_dicts(patch.get("agents"), "role")
    if new_agents:
        by_role = {
            a.role.value: a
            for a in (
                await db.scalars(select(Agent).where(Agent.company_id == company.id))
            ).all()
        }
        ceo = by_role.get(AgentRole.ceo.value)
        for spec in new_agents:
            try:
                role = AgentRole(spec.get("role", "custom"))
            except ValueError:
                role = AgentRole.custom
            agent = by_role.get(role.value)
            if agent is None:
                # Add a new functional agent, wired under the CEO.
                agent = Agent(
                    company_id=company.id,
                    role=role,
                    name=str(spec.get("name") or role.value.title())[:255],
                    system_prompt=str(spec.get("responsibility") or ""),
                    autonomy_level=_parse_autonomy(spec.get("autonomy_level")),
                    monthly_budget_cents=_as_int(spec.get("monthly_budget_cents"), None),
                    reports_to_agent_id=ceo.id if (ceo and role is not AgentRole.ceo) else None,
                )
                db.add(agent)
                await db.flush()
                by_role[role.value] = agent
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
                if "monthly_budget_cents" in spec:
                    agent.monthly_budget_cents = _as_int(
                        spec.get("monthly_budget_cents"), agent.monthly_budget_cents
                    )
        await db.flush()

    reply = patch.get("reply")
    return {
        "reply": str(reply) if reply else "Done — I've updated the plan.",
        "cost_estimate_cents": _as_int(patch.get("monthly_cost_estimate_cents"), None),
    }


async def launch(db: AsyncSession, *, company: Company) -> uuid.UUID | None:
    """Seed governance, activate the company, and create the root CEO run."""
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

    company.status = CompanyStatus.active
    task_id = await orchestrator.create_launch_run(db, company.id)
    await db.flush()
    return task_id
