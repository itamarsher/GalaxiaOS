"""Resolve the configured :class:`DomainRegistrar`.

The runtime calls :func:`get_registrar` and never imports a concrete registrar
directly. Selection is driven by ``settings.domain_registrar`` (env
``ABOS_DOMAIN_REGISTRAR``):

- ``simulated`` (default) — no real registrar; :func:`get_registrar` returns
  ``None`` and the ``register_domain`` tool reports the capability is unsupported.
- ``rdap`` — real availability via RDAP; purchase is simulated (no paid vendor).
- ``namecheap`` — real availability + REAL purchase via the Namecheap API
  (credential-gated; verify in sandbox first).
"""

from __future__ import annotations

from app.config import settings
from app.integrations.base import DomainRegistrar


def get_registrar(name: str | None = None) -> DomainRegistrar | None:
    """Return the configured domain registrar, or ``None`` if none is wired.

    ``name`` overrides ``settings.domain_registrar`` when given. There is no
    simulated registrar: the default (``simulated``) returns ``None`` so the
    ``register_domain`` tool reports the capability is unsupported instead of
    fabricating an availability check or registration. Unknown names raise
    ``ValueError`` so a misconfiguration fails loudly rather than silently spending
    against the wrong vendor.
    """
    key = (name or settings.domain_registrar).strip().lower()

    if key == "simulated":
        return None
    if key == "rdap":
        from app.integrations.rdap import RdapRegistrar

        return RdapRegistrar()
    if key == "namecheap":
        from app.integrations.namecheap import NamecheapRegistrar

        return NamecheapRegistrar()
    raise ValueError(f"unknown domain registrar: {key!r}")
