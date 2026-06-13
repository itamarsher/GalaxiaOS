"""Shared TLD pricing + reserved-name rules for domain registrars.

Live registrars vary their pricing per request; for quoting we use a small,
deterministic TLD table so estimates (and the simulated path) are stable. A real
adapter may override with a live pricing call if desired.
"""

from __future__ import annotations

# Reserved/special-use TLDs that are never registrable (RFC 2606 + friends).
RESERVED_TLDS = frozenset({"test", "invalid", "example", "localhost"})

# Sought-after TLDs priced as "premium"; everything else is the common price.
PREMIUM_TLDS = frozenset({"ai", "io", "dev", "app", "co"})

COMMON_PRICE_CENTS = 1200  # ~$12 — .com/.net/.org and the long tail.
PREMIUM_PRICE_CENTS = 4000  # ~$40 — sought-after TLDs.


def tld(domain: str) -> str:
    return domain.rsplit(".", 1)[-1].strip().lower()


def is_registrable(domain: str) -> bool:
    """A syntactically registrable name (has a TLD, not reserved)."""
    normalized = domain.strip().lower()
    return bool(normalized) and "." in normalized and tld(normalized) not in RESERVED_TLDS


def price_cents(domain: str) -> int:
    return PREMIUM_PRICE_CENTS if tld(domain) in PREMIUM_TLDS else COMMON_PRICE_CENTS
