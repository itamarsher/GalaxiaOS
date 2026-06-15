"""Pure-function unit tests for the investment-review feature (no database)."""

from __future__ import annotations

import json

import pytest

from app.models.enums import InvestmentStance, InvestorPersona
from app.runtime.investor_prompts import INVESTOR_PERSONAS
from app.services import investors
from app.services.investors import (
    InvestorError,
    _as_list,
    _clamp_conviction,
    _parse_json,
    _to_stance,
)


# ── _parse_json ──────────────────────────────────────────────────────────────
def test_parse_json_handles_raw_json():
    payload = {"stance": "invest", "conviction": 80, "headline": "go"}
    assert _parse_json(json.dumps(payload)) == payload


def test_parse_json_handles_fenced_json_block():
    raw = '```json\n{"stance":"pass","conviction":10}\n```'
    assert _parse_json(raw) == {"stance": "pass", "conviction": 10}


def test_parse_json_handles_bare_fence():
    raw = '```\n{"stance":"conditional"}\n```'
    assert _parse_json(raw) == {"stance": "conditional"}


def test_parse_json_extracts_object_with_surrounding_prose():
    raw = 'Here is my verdict: {"stance":"invest"} — thanks!'
    assert _parse_json(raw) == {"stance": "invest"}


def test_parse_json_raises_when_no_object():
    with pytest.raises(InvestorError):
        _parse_json("no json here")


# ── INVESTOR_PERSONAS ────────────────────────────────────────────────────────
def test_personas_cover_all_three_members():
    assert set(INVESTOR_PERSONAS) == set(InvestorPersona)
    assert len(INVESTOR_PERSONAS) == 3


def test_each_prompt_mentions_json_and_contract():
    for persona, prompt in INVESTOR_PERSONAS.items():
        assert "JSON" in prompt, persona
        # The minified JSON contract keys must be present in every prompt.
        for key in ("stance", "conviction", "headline", "thesis", "strengths", "risks", "conditions"):
            assert key in prompt, (persona, key)


# ── stance mapping ───────────────────────────────────────────────────────────
def test_stance_mapping_pass_maps_to_pass_():
    assert _to_stance("pass") is InvestmentStance.pass_
    assert InvestmentStance.pass_.value == "pass"


def test_stance_mapping_known_values():
    assert _to_stance("invest") is InvestmentStance.invest
    assert _to_stance("conditional") is InvestmentStance.conditional
    assert _to_stance("INVEST") is InvestmentStance.invest
    assert _to_stance("  pass  ") is InvestmentStance.pass_


def test_stance_mapping_unknown_defaults_conditional():
    assert _to_stance("maybe") is InvestmentStance.conditional
    assert _to_stance(None) is InvestmentStance.conditional
    assert _to_stance(42) is InvestmentStance.conditional


# ── conviction clamp ─────────────────────────────────────────────────────────
def test_clamp_conviction_bounds():
    assert _clamp_conviction(150) == 100
    assert _clamp_conviction(-5) == 0
    assert _clamp_conviction(73) == 73
    assert _clamp_conviction("55") == 55


def test_clamp_conviction_bad_input_zero():
    assert _clamp_conviction(None) == 0
    assert _clamp_conviction("oops") == 0


# ── list coercion ────────────────────────────────────────────────────────────
def test_as_list_passthrough_and_none():
    assert _as_list(["a", "b"]) == ["a", "b"]
    assert _as_list("nope") is None
    assert _as_list(None) is None


def test_investor_error_is_exception():
    assert issubclass(investors.InvestorError, Exception)
