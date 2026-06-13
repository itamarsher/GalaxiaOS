"""Real domain availability via RDAP (Registration Data Access Protocol).

RDAP is the IETF successor to WHOIS. ``https://rdap.org`` bootstraps to the
authoritative server for any TLD — a **200** means the domain is registered, a
**404** means it is not (i.e. available). No credentials, no signup.

Network failures return ``None`` ("unknown") so callers can fall back to a safe
default rather than crash or guess.
"""

from __future__ import annotations

import httpx

RDAP_BASE = "https://rdap.org/domain"


def interpret_status(status_code: int) -> bool | None:
    """Map an RDAP HTTP status to availability (``True``/``False``/unknown)."""
    if status_code == 404:
        return True  # no registration record -> available
    if status_code == 200:
        return False  # registration exists -> taken
    return None  # 429/5xx/redirial oddities -> unknown


async def rdap_available(domain: str, *, timeout: float = 4.0) -> bool | None:
    """Return whether ``domain`` is available per RDAP, or ``None`` if unknown."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(
                f"{RDAP_BASE}/{domain.strip().lower()}",
                headers={"Accept": "application/rdap+json"},
            )
    except httpx.HTTPError:
        return None
    return interpret_status(resp.status_code)
