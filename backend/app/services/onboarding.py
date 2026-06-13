"""Company Builder: mission → objectives/OKRs → agent fleet → launch.

The generation LLM calls go through the same :class:`CostMeter` as runtime work,
so even company generation respects the founder's budget.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.providers.base import Message, ToolSpec
from app.providers.registry import get_provider
from app.runtime import orchestrator
from app.runtime.cost_meter import CostMeter
from app.runtime.prompts import MISSION_TO_PLAN_SYSTEM, PLAN_TO_ORG_SYSTEM
from app.services import apikeys
from app.services import governance as gov


class OnboardingError(Exception):
    pass


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        text = text.lstrip("json").strip().strip("`")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise OnboardingError("LLM did not return JSON")
    return json.loads(text[start : end + 1])


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
    api_key = await apikeys.get_plaintext_key(db, company_id=company.id, provider="anthropic")
    if not api_key:
        raise OnboardingError("Add a provider API key before generating the organization.")

    mission = await db.scalar(select(Mission).where(Mission.company_id == company.id))
    budget = await db.scalar(select(Budget).where(Budget.company_id == company.id))
    provider = get_provider("anthropic")
    meter = CostMeter(SessionLocal)

    # ── LLM #1: mission → plan ────────────────────────────────────────────────
    from app.config import settings

    plan_resp = await meter.run_llm(
        provider,
        api_key=api_key,
        company_id=company.id,
        agent_id=None,
        task_id=None,
        model=settings.model_planner,
        system=MISSION_TO_PLAN_SYSTEM,
        messages=[Message(role="user", content=mission.raw_text)],
        max_tokens=1500,
    )
    plan = _parse_json(plan_resp.text)

    mission.generated_summary = plan.get("summary")
    mission.business_model_assumptions = plan.get("business_model_assumptions")
    mission.target_market = plan.get("target_market")
    company.name = (plan.get("summary") or company.name)[:120]

    for i, obj in enumerate(plan.get("objectives", [])):
        objective = Objective(
            company_id=company.id,
            mission_id=mission.id,
            title=obj.get("title", f"Objective {i+1}")[:500],
            rationale=obj.get("rationale"),
            priority=obj.get("priority", i + 1),
        )
        db.add(objective)
        await db.flush()
        for kr in obj.get("key_results", []):
            db.add(
                KeyResult(
                    company_id=company.id,
                    objective_id=objective.id,
                    metric=kr.get("metric", "metric")[:255],
                    target_value=kr.get("target_value"),
                    unit=kr.get("unit"),
                )
            )

    # ── LLM #2: plan + budget → org design ────────────────────────────────────
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
        model=settings.model_planner,
        system=PLAN_TO_ORG_SYSTEM,
        messages=[Message(role="user", content=org_input)],
        max_tokens=1500,
    )
    org = _parse_json(org_resp.text)

    role_to_agent: dict[str, uuid.UUID] = {}
    for spec in org.get("agents", []):
        try:
            role = AgentRole(spec.get("role", "custom"))
        except ValueError:
            role = AgentRole.custom
        agent = Agent(
            company_id=company.id,
            role=role,
            name=spec.get("name", role.value.title()),
            system_prompt=spec.get("responsibility", ""),
            autonomy_level=_parse_autonomy(spec.get("autonomy_level")),
            monthly_budget_cents=spec.get("monthly_budget_cents"),
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
    return {
        "cost_estimate_cents": org.get("monthly_cost_estimate_cents"),
        "agent_roles": list(role_to_agent.keys()),
    }


def _parse_autonomy(value: str | None) -> AutonomyLevel:
    try:
        return AutonomyLevel(value)
    except (ValueError, TypeError):
        return AutonomyLevel.approve_required


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
