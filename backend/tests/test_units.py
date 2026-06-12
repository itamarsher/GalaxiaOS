"""Pure-function unit tests (no database required)."""

from __future__ import annotations

import uuid

from app.providers.base import Price, Usage
from app.runtime.breakers import loop_signature
from app.services.governance import _matches


def test_price_cost_cents_rounds_up_and_floors_at_one():
    price = Price(input_cents_per_mtok=500, output_cents_per_mtok=2500)
    # 1M in + 1M out = 500 + 2500 = 3000 cents
    assert price.cost_cents(Usage(input_tokens=1_000_000, output_tokens=1_000_000)) == 3000
    # Tiny usage rounds up to at least 1 cent
    assert price.cost_cents(Usage(input_tokens=1, output_tokens=1)) == 1
    # No usage = no charge
    assert price.cost_cents(Usage()) == 0


def test_policy_matcher_numeric_compare():
    rule = {"field": "amount_cents", "op": ">", "value": 10000}
    assert _matches(rule, {"amount_cents": 12000}) is True
    assert _matches(rule, {"amount_cents": 9000}) is False
    assert _matches(rule, {"amount_cents": None}) is False


def test_policy_matcher_tool_and_role():
    rule = {"tool": "register_domain", "role_in": ["growth", "ceo"]}
    assert _matches(rule, {"tool": "register_domain", "agent_role": "growth"}) is True
    assert _matches(rule, {"tool": "register_domain", "agent_role": "finance"}) is False
    assert _matches(rule, {"tool": "write_memory", "agent_role": "growth"}) is False


def test_loop_signature_is_stable_and_normalised():
    aid = uuid.uuid4()
    a = loop_signature(aid, "Grow   the  Pipeline")
    b = loop_signature(aid, "grow the pipeline")
    assert a == b
    assert loop_signature(uuid.uuid4(), "grow the pipeline") != a
