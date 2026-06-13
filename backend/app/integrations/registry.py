"""Resolve the configured :class:`DomainRegistrar`.

The runtime calls :func:`get_registrar` and never imports a concrete registrar
directly. Selection is driven by ``settings.domain_registrar`` (env
``ABOS_DOMAIN_REGISTRAR``):

- ``simulated`` (default) — offline, deterministic; no network, no real spend.
- ``rdap`` — real availability via RDAP; purchase is simulated (no paid vendor).
- ``namecheap`` — real availability + REAL purchase via the Namecheap API
  (credential-gated; verify in sandbox first).
"""

from __future__ import annotations

from app.config import settings
from app.integrations.base import DomainRegistrar


def get_registrar(name: str | None = None) -> DomainRegistrar:
    """Return the configured domain registrar (defaults to simulated).

    ``name`` overrides ``settings.domain_registrar`` when given. Unknown names
    raise ``ValueError`` so a misconfiguration fails loudly rather than silently
    spending against the wrong vendor.
    """
    key = (name or settings.domain_registrar).strip().lower()

    if key == "simulated":
        from app.integrations.simulated import SimulatedRegistrar

        return SimulatedRegistrar()
    if key == "rdap":
        from app.integrations.rdap import RdapRegistrar

        return RdapRegistrar()
    if key == "namecheap":
        from app.integrations.namecheap import NamecheapRegistrar

        return NamecheapRegistrar()
    raise ValueError(f"unknown domain registrar: {key!r}")
