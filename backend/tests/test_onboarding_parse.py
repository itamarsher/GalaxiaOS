"""Pure-function tests for onboarding LLM JSON parsing."""

from __future__ import annotations

import pytest

from app.providers.base import LLMResponse
from app.services.onboarding import OnboardingError, _as_dicts, _as_int, _parse_llm_json


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


def test_malformed_json_raises_onboarding_error():
    # Generation forces structured JSON at the provider, so this is rare — but if
    # a provider returns invalid JSON, fail with a handled error, not a 500.
    with pytest.raises(OnboardingError):
        _parse_llm_json(_resp('{"a" 1, "b": 2}'))


def test_no_json_raises_onboarding_error():
    with pytest.raises(OnboardingError):
        _parse_llm_json(_resp("sorry, I cannot help with that"))


def test_as_dicts_coerces_bare_strings():
    # JSON mode can return agents/objectives as a list of strings — coerce to
    # dicts keyed by the primary field so persistence never crashes.
    assert _as_dicts(["ceo", "growth"], "role") == [{"role": "ceo"}, {"role": "growth"}]
    assert _as_dicts([{"role": "ceo"}], "role") == [{"role": "ceo"}]
    # mixed + junk: keep dicts and strings, drop everything else
    assert _as_dicts([{"a": 1}, "x", 5, None], "role") == [{"a": 1}, {"role": "x"}]
    # non-list inputs degrade to empty
    assert _as_dicts(None, "role") == []
    assert _as_dicts("ceo", "role") == []


def test_as_int_coerces_or_falls_back():
    assert _as_int(5, 0) == 5
    assert _as_int("12345", None) == 12345
    assert _as_int("50.0", None) == 50
    assert _as_int(None, 7) == 7
    assert _as_int("not a number", None) is None
    assert _as_int(True, 3) == 3  # bools are not valid cents
