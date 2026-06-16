"""Pure-function tests for onboarding LLM JSON parsing."""

from __future__ import annotations

import pytest

from app.providers.base import LLMResponse
from app.services.onboarding import OnboardingError, _parse_llm_json


def _resp(text: str, stop_reason: str = "end_turn") -> LLMResponse:
    return LLMResponse(text=text, stop_reason=stop_reason)


def test_parses_plain_json():
    assert _parse_llm_json(_resp('{"a": 1, "b": "x"}')) == {"a": 1, "b": "x"}


def test_strips_code_fences():
    assert _parse_llm_json(_resp('```json\n{"a": 1}\n```')) == {"a": 1}


def test_extracts_object_from_surrounding_prose():
    # Trailing prose used to break the naive rfind("}") slicing.
    text = 'Here is your org: {"agents": []}. Hope that helps!'
    assert _parse_llm_json(_resp(text)) == {"agents": []}


def test_ignores_braces_inside_strings():
    text = '{"note": "use {curly} braces"}'
    assert _parse_llm_json(_resp(text)) == {"note": "use {curly} braces"}


def test_takes_first_complete_object_not_dangling_braces():
    # A second, truncated object after the first must not corrupt parsing.
    text = '{"ok": true} {"truncated":'
    assert _parse_llm_json(_resp(text)) == {"ok": True}


@pytest.mark.parametrize("stop_reason", ["max_tokens", "length"])
def test_truncated_response_raises_specific_error(stop_reason):
    # The model hit the token ceiling: report truncation, not "malformed JSON".
    resp = _resp('{"agents": [{"name": "CE', stop_reason=stop_reason)
    with pytest.raises(OnboardingError, match="cut off"):
        _parse_llm_json(resp)


def test_unescaped_quote_in_value_recovered_via_repair():
    # The production failure mode: an unescaped quote inside a free-text field
    # makes the whole response invalid JSON (and desyncs brace extraction).
    # The repair fallback recovers the structure instead of failing generation.
    text = (
        '{"agents": [{"role": "ceo", "name": "CEO", '
        '"responsibility": "Own the "north star" metric"}], '
        '"monthly_cost_estimate_cents": 5000}'
    )
    out = _parse_llm_json(_resp(text))
    assert out["monthly_cost_estimate_cents"] == 5000
    assert out["agents"][0]["role"] == "ceo"


def test_no_json_raises_onboarding_error():
    with pytest.raises(OnboardingError):
        _parse_llm_json(_resp("sorry, I cannot help with that"))
