"""Resolve the configured :class:`DomainRegistrar`.

The runtime calls :func:`get_registrar` and never imports a concrete registrar
directly. Selection is driven by ``settings.domain_registrar`` (env
``ABOS_DOMAIN_REGISTRAR``); the default is the simulated registrar. A real
integration registers here under its own key — no runtime code changes.
"""

from __future__ import annotations

from app.config import settings
from app.integrations.base import DomainRegistrar
from app.integrations.simulated import SimulatedRegistrar


def get_registrar(name: str | None = None) -> DomainRegistrar:
    """Return the configured domain registrar (defaults to simulated).

    ``name`` overrides ``settings.domain_registrar`` when given. Unknown names
    raise ``ValueError`` so a misconfiguration fails loudly rather than silently
    spending against the wrong vendor.
    """
    key = (name or settings.domain_registrar).strip().lower()

    if key == "simulated":
        return SimulatedRegistrar()

    # Real registrars slot in here, e.g.:
    #   if key == "namecheap":
    #       from app.integrations.namecheap import NamecheapRegistrar
    #       return NamecheapRegistrar()
    raise ValueError(f"unknown domain registrar: {key!r}")
