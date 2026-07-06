"""The graphic-designer (design) agent: fleet wiring + design-tool helpers."""

from __future__ import annotations

from app.models.enums import AgentRole
from app.runtime.prompts import ROLE_DESCRIPTIONS
from app.runtime.tools import design as design_tools
from app.services import onboarding


def test_design_role_exists_and_has_a_prompt():
    assert AgentRole("design") is AgentRole.design
    desc = ROLE_DESCRIPTIONS[AgentRole.design]
    assert "Nano Banana" in desc
    assert "generate_image" in desc and "generate_video" in desc


def test_default_fleet_includes_graphic_designer():
    designers = [s for s in onboarding._DEFAULT_FLEET if s["role"] == "design"]
    assert len(designers) == 1
    assert "Nano Banana" in designers[0]["responsibility"]


def test_design_role_has_a_budget_weight():
    assert AgentRole.design in onboarding._ROLE_BUDGET_WEIGHTS


def test_design_tools_are_registered():
    assert set(design_tools.HANDLERS) == {"generate_image", "generate_video"}
    spec_names = {s.name for s in design_tools.SPECS}
    assert spec_names == {"generate_image", "generate_video"}


def test_compose_prompt_blends_brand_when_on_brand():
    out = design_tools._compose_prompt("a hero banner", "Palette: navy + gold.", on_brand=True)
    assert "Palette: navy + gold." in out
    assert "a hero banner" in out


def test_compose_prompt_skips_brand_when_off_brand_or_empty():
    assert design_tools._compose_prompt("x", "brand", on_brand=False) == "x"
    assert design_tools._compose_prompt("x", "   ", on_brand=True) == "x"


def test_asset_filename_applies_mime_extension():
    assert design_tools._asset_filename("hero-banner", "p", "image/png") == "hero-banner.png"
    assert design_tools._asset_filename("teaser", "p", "video/mp4") == "teaser.mp4"
    # Already-correct extension is not doubled up.
    assert design_tools._asset_filename("logo.png", "p", "image/png") == "logo.png"
    # Falls back to the prompt when no filename is given.
    assert design_tools._asset_filename(None, "a red fox", "image/jpeg").endswith(".jpg")
