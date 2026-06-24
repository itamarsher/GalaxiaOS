"""Unit tests for the closed perceive->act->measure->learn agent loop.

Pure, DB-free: these exercise the prompt template, the tool registry, and the
reputation-driven model-tier escalation helper.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.runtime.backends import native
from app.runtime.prompts import (
    AGENT_LOOP_SYSTEM,
    DEFAULT_COMPANY_PLAYBOOK,
    effective_playbook,
    render_agent_system,
)
from app.runtime.tools import TOOL_SPECS
from app.runtime.tools.base import clip


def test_system_prompt_has_all_slots() -> None:
    for slot in ("{memory}", "{metrics}", "{role_desc}", "{directive}", "{playbook}"):
        assert slot in AGENT_LOOP_SYSTEM


def test_render_agent_system_fills_all_slots() -> None:
    rendered = render_agent_system(
        role_desc="You are the CEO agent.",
        agent_directive="You own the launch.",
        playbook=None,  # falls back to the platform default
        mission="Build something great.",
        goal="Plan the launch.",
        memory="- learning: pricing matters",
        metrics="No real-world metrics yet.",
        skills="- cold-email-outreach: run a campaign",
    )
    assert "pricing matters" in rendered
    assert "Plan the launch." in rendered
    assert "You own the launch." in rendered  # per-agent directive injected
    assert "standing operating directives" in rendered  # default playbook injected
    assert "cold-email-outreach" in rendered  # skills index injected
    # All named format slots are consumed (a literal "{role, goal}" example may remain).
    for slot in ("{role_desc}", "{directive}", "{playbook}", "{mission}", "{goal}", "{memory}", "{metrics}", "{skills}"):
        assert slot not in rendered


def test_parallel_and_report_tools_registered() -> None:
    names = {spec.name for spec in TOOL_SPECS}
    for expected in {"dispatch_tasks", "create_report", "load_skill"}:
        assert expected in names


def test_clip_flags_only_when_actually_truncated() -> None:
    # Fits within the limit → returned verbatim, no spurious "truncated" marker.
    assert clip("short", 100) == "short"
    assert clip("exactly-ten", len("exactly-ten")) == "exactly-ten"
    assert "truncated" not in clip("short", 100)
    # Falsy inputs are safe and unflagged.
    assert clip("", 100) == ""
    assert clip(None, 100) == ""
    # Over the limit → cut to the limit and flagged as incomplete, reporting the
    # number of omitted units so the receiving agent knows it's partial.
    out = clip("abcdefghij", 4)
    assert out.startswith("abcd")
    assert "truncated" in out
    assert "6 more characters" in out
    # Unit label is configurable (e.g. list items).
    assert "3 more files" in clip("a" * 10, 7, unit="files")


def test_effective_playbook_falls_back_to_default() -> None:
    assert effective_playbook(None) == DEFAULT_COMPANY_PLAYBOOK
    assert effective_playbook("   ") == DEFAULT_COMPANY_PLAYBOOK
    assert effective_playbook("Custom rules.") == "Custom rules."


def test_render_uses_custom_playbook_and_omits_empty_directive() -> None:
    rendered = render_agent_system(
        role_desc="You are the Growth agent.",
        agent_directive="   ",  # blank -> no directive block
        playbook="ALWAYS ship on Fridays.",
        mission="m",
        goal="g",
        memory="x",
        metrics="y",
    )
    assert "ALWAYS ship on Fridays." in rendered
    assert "standing operating directives" not in rendered  # default not used
    assert "company-specific directive" not in rendered  # empty directive omitted


def test_new_tools_registered() -> None:
    names = {spec.name for spec in TOOL_SPECS}
    for expected in {"read_metrics", "record_metric", "web_search", "collect_results"}:
        assert expected in names


@pytest.fixture
def _escalation_on(monkeypatch):
    monkeypatch.setattr(settings, "reputation_model_escalation", True)
    monkeypatch.setattr(settings, "reputation_escalate_below", 0.4)


def test_escalate_tier_low_trust_bumps_cheap_to_planner(_escalation_on) -> None:
    assert native._escalate_tier("cheap", 0.1) == "planner"


def test_escalate_tier_low_trust_bumps_planner_to_strategic(_escalation_on) -> None:
    assert native._escalate_tier("planner", 0.1) == "strategic"


def test_escalate_tier_strategic_is_capped(_escalation_on) -> None:
    assert native._escalate_tier("strategic", 0.1) == "strategic"


def test_escalate_tier_high_trust_unchanged(_escalation_on) -> None:
    assert native._escalate_tier("cheap", 0.9) == "cheap"
    assert native._escalate_tier("planner", 0.9) == "planner"


def test_escalate_tier_none_trust_unchanged(_escalation_on) -> None:
    assert native._escalate_tier("cheap", None) == "cheap"


def test_escalate_tier_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "reputation_model_escalation", False)
    assert native._escalate_tier("cheap", 0.0) == "cheap"
