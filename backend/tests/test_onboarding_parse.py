"""Pure-function tests for onboarding LLM JSON parsing."""

from __future__ import annotations

import pytest

from app.services.onboarding import OnboardingError, _parse_json


def test_parses_plain_json():
    assert _parse_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_strips_code_fences():
    text = '```json\n{"a": 1}\n```'
    assert _parse_json(text) == {"a": 1}


def test_extracts_object_from_surrounding_prose():
    # Trailing prose used to break the naive rfind("}") slicing.
    text = 'Here is your org: {"agents": []}. Hope that helps!'
    assert _parse_json(text) == {"agents": []}


def test_ignores_braces_inside_strings():
    text = '{"note": "use {curly} braces"}'
    assert _parse_json(text) == {"note": "use {curly} braces"}


def test_takes_first_complete_object_not_dangling_braces():
    # A second, truncated object after the first must not corrupt parsing.
    text = '{"ok": true} {"truncated":'
    assert _parse_json(text) == {"ok": True}


def test_malformed_json_raises_onboarding_error():
    # Balanced braces but invalid contents -> handled error, not a raw 500.
    with pytest.raises(OnboardingError):
        _parse_json('{"a" 1, "b": 2}')


def test_no_json_raises_onboarding_error():
    with pytest.raises(OnboardingError):
        _parse_json("sorry, I cannot help with that")
