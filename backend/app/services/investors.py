"""Investment review — three agentic investor personas weigh in at onboarding.

After the plan + org are generated, three investor personas each produce a
structured verdict on the venture. The LLM calls go through the same
:class:`CostMeter` as the rest of the system, so even the review respects the
founder's budget. Each persona's call is independent and resilient: a single
unparseable response degrades to a placeholder row rather than aborting the
whole review.
"""

from __future__ import annotations

import json

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import Company, InvestmentReview, KeyResult, Mission, Objective
from app.models.enums import InvestmentStance
from app.observability import get_logger
from app.providers.base import Message
from app.runtime.cost_meter import CostMeter
from app.runtime.investor_prompts import INVESTOR_PERSONAS
from app.services import apikeys

_log = get_logger("abos.investors")


class InvestorError(Exception):
    pass


def _parse_json(text: str) -> dict:
    """Best-effort JSON extraction (mirrors ``onboarding._parse_json``)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        text = text.lstrip("json").strip().strip("`")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise InvestorError("LLM did not return JSON")
    return json.loads(text[start : end + 1])


def _to_stance(value: object) -> InvestmentStance:
    """Map a stance string to the enum; ``"pass"`` -> ``pass_``, else ``conditional``."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "pass":
            return InvestmentStance.pass_
        try:
            return InvestmentStance(normalized)
        except ValueError:
            pass
    return InvestmentStance.conditional


def _clamp_conviction(value: object) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, n))


def _as_list(value: object) -> list | None:
    return value if isinstance(value, list) else None


async def _build_deal_memo(db: AsyncSession, *, company: Company) -> str:
    """Assemble the compact JSON "deal memo" the investors review.

    The budget is deliberately left out: the founder can add more later, so the
    investors should weigh the venture on its merits rather than a fixed spend
    level (the personas are instructed not to treat budget as a constraint).
    """
    mission = await db.scalar(select(Mission).where(Mission.company_id == company.id))

    objectives = (
        await db.scalars(
            select(Objective)
            .where(Objective.company_id == company.id)
            .order_by(Objective.priority)
        )
    ).all()

    objective_memos = []
    for obj in objectives:
        krs = (
            await db.scalars(select(KeyResult).where(KeyResult.objective_id == obj.id))
        ).all()
        objective_memos.append(
            {
                "title": obj.title,
                "rationale": obj.rationale,
                "key_results": [
                    {
                        "metric": kr.metric,
                        "target_value": kr.target_value,
                        "unit": kr.unit,
                    }
                    for kr in krs
                ],
            }
        )

    memo = {
        "company_name": company.name,
        "summary": mission.generated_summary if mission else None,
        "target_market": mission.target_market if mission else None,
        "business_model_assumptions": (
            mission.business_model_assumptions if mission else None
        ),
        "objectives": objective_memos,
    }
    return json.dumps(memo)


async def review(db: AsyncSession, *, company: Company) -> list[InvestmentReview]:
    """Run the three investor personas and persist their verdicts (idempotent)."""
    resolved = await apikeys.resolve_provider(db, company_id=company.id)
    if resolved is None:
        raise InvestorError("Add a provider API key before running the investment review.")
    provider, api_key = resolved
    model = settings.investor_model or provider.default_models["planner"]

    deal_memo = await _build_deal_memo(db, company=company)

    # Idempotent re-run: drop any prior verdicts for this company first.
    await db.execute(
        delete(InvestmentReview).where(InvestmentReview.company_id == company.id)
    )

    meter = CostMeter(SessionLocal)
    reviews: list[InvestmentReview] = []

    for persona, system in INVESTOR_PERSONAS.items():
        try:
            resp = await meter.run_llm(
                provider,
                api_key=api_key,
                company_id=company.id,
                agent_id=None,
                task_id=None,
                model=model,
                system=system,
                messages=[Message(role="user", content=deal_memo)],
                max_tokens=1200,
            )
        except Exception:  # noqa: BLE001 - one persona must not abort the rest
            _log.exception("investor LLM call failed for persona %s", persona.value)
            review_row = InvestmentReview(
                company_id=company.id,
                persona=persona,
                stance=InvestmentStance.conditional,
                conviction=0,
                headline="(review unavailable)",
                thesis="The investor call failed to complete.",
                model=model,
            )
            db.add(review_row)
            reviews.append(review_row)
            continue

        try:
            data = _parse_json(resp.text)
            review_row = InvestmentReview(
                company_id=company.id,
                persona=persona,
                stance=_to_stance(data.get("stance")),
                conviction=_clamp_conviction(data.get("conviction")),
                headline=(data.get("headline") or "")[:500],
                thesis=data.get("thesis") or "",
                strengths=_as_list(data.get("strengths")),
                risks=_as_list(data.get("risks")),
                conditions=_as_list(data.get("conditions")),
                model=model,
            )
        except Exception:  # noqa: BLE001 - bad JSON degrades to a placeholder row
            _log.warning("could not parse investor response for persona %s", persona.value)
            review_row = InvestmentReview(
                company_id=company.id,
                persona=persona,
                stance=InvestmentStance.conditional,
                conviction=0,
                headline="(unparseable response)",
                thesis=resp.text,
                model=model,
            )
        db.add(review_row)
        reviews.append(review_row)

    await db.flush()
    return reviews
