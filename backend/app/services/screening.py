"""Lightweight acceptability screening for platform-funded (free-tier) missions.

When the platform funds a founder's compute (managed free tier), a mission is
also an abuse vector: spam farms, fraud, malware, targeted harassment. This is a
cheap, dependency-free, deterministic denylist gate — deliberately conservative
so it never needs a key or a network call. It is applied ONLY when the platform
is footing the bill; a founder on their own key can pursue anything their own
provider permits.

It is a backstop, not the whole safety story: the runtime also has governance,
the external-comms approval gate, and per-founder spend caps. Keep it blunt and
low-false-positive; borderline cases pass here and are caught downstream.
"""

from __future__ import annotations

import re

# Phrases that indicate a clearly-disallowed intent. Matched case-insensitively
# as whole words/phrases. Intentionally small and high-precision.
_DISALLOWED = [
    r"child (?:sexual|porn|abuse)",
    r"\bcsam\b",
    r"credit card (?:dump|skimm)",
    r"stolen (?:credit cards?|identit|data)",
    r"\bcarding\b",
    r"\bransomware\b",
    r"\bmalware\b",
    r"\bbotnet\b",
    r"\bphishing\b",
    r"\bddos\b",
    r"launder(?:ing)? money",
    r"money laundering",
    r"\bhitman\b",
    r"human trafficking",
    r"sex trafficking",
    r"\bfentanyl\b",
    r"sell(?:ing)? (?:meth|heroin|cocaine|drugs)\b",
    r"counterfeit (?:money|currency|cash|notes)",
    r"bioweapon|chemical weapon|nerve agent",
]

_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _DISALLOWED]


def screen_mission(text: str) -> tuple[bool, str | None]:
    """Return ``(ok, reason)``. ``ok=False`` blocks a free-tier launch.

    ``reason`` is a founder-facing message when blocked.
    """
    if not text:
        return True, None
    for pat in _PATTERNS:
        if pat.search(text):
            return (
                False,
                "This mission can't run on the free platform tier because it appears to "
                "involve disallowed activity. If this is a mistake, bring your own model "
                "key to run it on your own account.",
            )
    return True, None
