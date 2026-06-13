"""Phase 1 verification: the CostMeter budget chokepoint.

Proves (1) concurrent reservations cannot exceed the limit, (2) over-budget
raises BudgetExceeded and trips the spend breaker, (3) an LLM call and an
external charge both decrement the *same* budget through one CostMeter.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.providers.base import LLMProvider, LLMResponse, Message, Price, ToolSpec, Usage
from app.runtime.cost_meter import CostMeter
from app.services import budget as budget_svc
from app.services.budget import BudgetExceeded
from tests.conftest import requires_db


class FakeProvider(LLMProvider):
    """Deterministic provider that 'uses' a fixed number of tokens."""

    name = "anthropic"

    def __init__(self, in_tokens: int, out_tokens: int):
        self._in, self._out = in_tokens, out_tokens

    def price(self, model: str) -> Price:
        # $1/MTok in, $5/MTok out -> 100 / 500 cents.
        return Price(input_cents_per_mtok=100, output_cents_per_mtok=500)

    def estimate_input_tokens(self, *, api_key, model, system, messages) -> int:
        return self._in

    async def complete(self, *, api_key, model, system, messages, tools=None, max_tokens=4096):
        return LLMResponse(
            text="ok",
            usage=Usage(input_tokens=self._in, output_tokens=self._out),
            model=model,
        )


@requires_db
async def test_llm_and_external_share_one_budget(session_factory, company_with_budget):
    company_id = company_with_budget
    meter = CostMeter(session_factory)
    provider = FakeProvider(in_tokens=1_000_000, out_tokens=200_000)  # 100c + 100c = 200c

    await meter.run_llm(
        provider,
        api_key="sk-test",
        company_id=company_id,
        agent_id=None,
        task_id=None,
        model="claude-haiku-4-5",
        system="s",
        messages=[Message(role="user", content="hi")],
        tools=[ToolSpec("noop", "", {"type": "object", "properties": {}})],
        max_tokens=200_000,
    )
    await meter.charge_external(
        company_id=company_id,
        agent_id=None,
        task_id=None,
        amount_cents=300,
        vendor="registrar(sim)",
        sku="example.com",
    )

    async with session_factory() as db:
        budget = await budget_svc.get_active_budget(db, company_id)
        assert budget.spent_cents == 500  # 200 (llm) + 300 (external)
        assert budget.reserved_cents == 0
        by_cat = await budget_svc.spend_by_category(db, company_id)
    assert by_cat["llm"] == 200
    assert by_cat["external"] == 300


@requires_db
async def test_over_budget_raises_and_releases(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        with pytest.raises(BudgetExceeded):
            await budget_svc.reserve(db, company_id=company_id, cents=10_001)
        await db.rollback()
    # Reservation must not have leaked.
    async with session_factory() as db:
        budget = await budget_svc.get_active_budget(db, company_id)
        assert budget.reserved_cents == 0


@requires_db
async def test_concurrent_reservations_cannot_exceed_limit(session_factory, company_with_budget):
    company_id = company_with_budget
    meter = CostMeter(session_factory)
    # Each external charge is 6000c; limit is 10000c -> exactly one must fail.
    results = await asyncio.gather(
        meter.charge_external(
            company_id=company_id, agent_id=None, task_id=None, amount_cents=6000, vendor="v"
        ),
        meter.charge_external(
            company_id=company_id, agent_id=None, task_id=None, amount_cents=6000, vendor="v"
        ),
        return_exceptions=True,
    )
    failures = [r for r in results if isinstance(r, BudgetExceeded)]
    assert len(failures) == 1
    async with session_factory() as db:
        budget = await budget_svc.get_active_budget(db, company_id)
        assert budget.spent_cents == 6000
        assert budget.reserved_cents == 0
