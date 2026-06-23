"""Unit tests for the closed perceive->act->measure->learn agent loop.

Pure, DB-free: these exercise the prompt template, the tool registry, and the
reputation-driven model-tier escalation helper.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.runtime.backends import native
from app.runtime.prompts import AGENT_LOOP_SYSTEM
from app.runtime.tools import TOOL_SPECS


def test_system_prompt_has_memory_and_metrics_slots() -> None:
    assert "{memory}" in AGENT_LOOP_SYSTEM
    assert "{metrics}" in AGENT_LOOP_SYSTEM


def test_system_prompt_formats_with_all_slots() -> None:
    rendered = AGENT_LOOP_SYSTEM.format(
        role_desc="You are the CEO agent.",
        mission="Build something great.",
        goal="Plan the launch.",
        memory="- learning: pricing matters",
        metrics="No real-world metrics yet.",
        skills="- cold-email-outreach: run a campaign",
    )
    assert "pricing matters" in rendered
    assert "Plan the launch." in rendered
    assert "cold-email-outreach" in rendered
    # All named format slots are consumed (a literal "{role, goal}" example may remain).
    for slot in ("{role_desc}", "{mission}", "{goal}", "{memory}", "{metrics}", "{skills}"):
        assert slot not in rendered


def test_parallel_and_report_tools_registered() -> None:
    names = {spec.name for spec in TOOL_SPECS}
    for expected in {"dispatch_tasks", "create_report", "load_skill"}:
        assert expected in names


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
