"""Tests for the sales tools module (DB-free)."""

from __future__ import annotations

import pytest

from app.runtime.tools import TOOL_SPECS
from app.runtime.tools.sales import (
    DEAL_STAGES,
    HANDLERS,
    SPECS,
    format_deal_summary,
    format_lead_summary,
    validate_stage,
)

SALES_TOOL_NAMES = ("log_lead", "update_deal", "schedule_followup")


def test_sales_tools_registered():
    names = {s.name for s in TOOL_SPECS}
    for expected in SALES_TOOL_NAMES:
        assert expected in names


def test_specs_have_object_schema():
    for spec in SPECS:
        assert spec.input_schema["type"] == "object"
        assert "properties" in spec.input_schema


def test_handlers_match_specs():
    assert set(HANDLERS) == {s.name for s in SPECS}


def test_spec_names_are_exactly_assigned():
    assert {s.name for s in SPECS} == set(SALES_TOOL_NAMES)


def test_validate_stage_normalizes():
    assert validate_stage("WON") == "won"
    assert validate_stage(" qualified ") == "qualified"
    for stage in DEAL_STAGES:
        assert validate_stage(stage) == stage


def test_validate_stage_rejects_unknown():
    with pytest.raises(ValueError):
        validate_stage("negotiating")


def test_format_lead_summary_includes_optional_fields():
    summary = format_lead_summary(
        {"name": "Ada", "email": "ada@x.io", "company": "Analytical", "source": "ref"}
    )
    assert "name=Ada" in summary
    assert "email=ada@x.io" in summary
    assert "company=Analytical" in summary
    assert "source=ref" in summary


def test_format_lead_summary_omits_missing_fields():
    summary = format_lead_summary({"name": "Ada"})
    assert summary == "name=Ada"


def test_format_deal_summary_with_and_without_amount():
    assert format_deal_summary("Ada", "won", 12345) == "lead=Ada -> stage=won ($123.45)"
    assert format_deal_summary("Ada", "new", None) == "lead=Ada -> stage=new"
