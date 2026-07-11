"""Free-tier mission screening (pure, no DB)."""

from __future__ import annotations

import pytest

from app.services.screening import screen_mission


@pytest.mark.parametrize(
    "mission",
    [
        "Build the best vulnerability management platform for SMBs.",
        "A marketplace for handmade furniture with same-day delivery.",
        "An AI tutor that helps kids learn math.",
        "",
    ],
)
def test_clean_missions_pass(mission):
    ok, reason = screen_mission(mission)
    assert ok is True
    assert reason is None


@pytest.mark.parametrize(
    "mission",
    [
        "A service for carding and selling stolen credit cards.",
        "Distribute ransomware to companies and demand payment.",
        "A platform to launder money for clients.",
        "Sell fentanyl and cocaine online, discreetly shipped.",
    ],
)
def test_disallowed_missions_are_blocked(mission):
    ok, reason = screen_mission(mission)
    assert ok is False
    assert reason and "free platform tier" in reason


def test_screen_is_case_insensitive():
    ok, _ = screen_mission("We build RANSOMWARE as a service.")
    assert ok is False
