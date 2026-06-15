"""Tests for the marketing tools module (DB-free / network-free)."""

from __future__ import annotations

from app.integrations.marketing import published_url, slugify
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


def test_slug_and_url_are_deterministic():
    title = "My First Launch Post!"
    assert slugify(title) == slugify(title)
    assert published_url("blog", title) == published_url("blog", title)
    assert slugify(title) == "my-first-launch-post"
    assert published_url("blog", title).endswith("/blog/my-first-launch-post")


def test_slug_handles_empty_title():
    # Symbol-only / empty titles still produce a stable, non-empty slug.
    assert slugify("!!!") == slugify("!!!")
    assert slugify("!!!")
