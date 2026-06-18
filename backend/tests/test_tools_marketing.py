"""Tests for the marketing tools module (DB-free / network-free).

The marketing tools have no CMS/social/ad provider behind them, so they report the
capability is unsupported instead of fabricating a published URL / scheduled post /
launched campaign — and ``run_ad_campaign`` does NOT charge the budget.
"""

from __future__ import annotations

import pytest

from app.runtime.tools import TOOL_SPECS
from app.runtime.tools import marketing as marketing_mod

_MARKETING_TOOLS = {"publish_content", "schedule_social_post", "run_ad_campaign"}


def test_marketing_tools_registered():
    names = {s.name for s in TOOL_SPECS}
    for expected in _MARKETING_TOOLS:
        assert expected in names


def test_every_marketing_spec_has_object_schema():
    for spec in marketing_mod.SPECS:
        assert spec.input_schema["type"] == "object"
        assert "properties" in spec.input_schema


def test_run_ad_campaign_requires_amount_cents():
    spec = next(s for s in marketing_mod.SPECS if s.name == "run_ad_campaign")
    assert "amount_cents" in spec.input_schema["required"]
    assert "amount_cents" in spec.input_schema["properties"]


def test_handlers_match_specs():
    spec_names = {s.name for s in marketing_mod.SPECS}
    assert set(marketing_mod.HANDLERS.keys()) == spec_names


# NB: publish_content / connect_domain are now real capabilities (gated on a
# configured Cloudflare host + per-company credentials), so their "unsupported when
# unconfigured" path is covered in test_sites.py where the resolver is mocked. The
# tools below have no provider at all and are unconditionally unsupported.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args",
    [
        ("schedule_social_post", {"platform": "x", "content": "hi"}),
        ("run_ad_campaign", {"platform": "x", "objective": "signups", "amount_cents": 5000}),
    ],
)
async def test_handlers_report_unsupported(name, args):
    # ctx is unused — in particular run_ad_campaign must NOT reach a cost meter.
    outcome = await marketing_mod.HANDLERS[name](None, None, agent=None, task=None, args=args)
    assert outcome.is_error is True
    assert "not supported" in outcome.observation
    assert "request_capability" in outcome.observation


@pytest.mark.asyncio
async def test_run_ad_campaign_does_not_charge_budget():
    class _ExplodingMeter:
        async def charge_external(self, *a, **k):  # pragma: no cover - must not run
            raise AssertionError("run_ad_campaign must not charge when unsupported")

    class _Ctx:
        cost_meter = _ExplodingMeter()

    outcome = await marketing_mod.HANDLERS["run_ad_campaign"](
        None, _Ctx(), agent=None, task=None,
        args={"platform": "x", "objective": "signups", "amount_cents": 5000},
    )
    assert outcome.is_error is True
