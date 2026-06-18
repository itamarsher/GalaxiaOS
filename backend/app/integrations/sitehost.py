"""Site-hosting seam — where a generated landing page actually gets served.

A :class:`SiteHost` publishes a single HTML page to a real static host and can
attach a custom domain to it. Like the registrar seam there is deliberately NO
simulated host: fabricating a "published" URL lets agents believe a page went live
when it did not. Until a real adapter is wired, :func:`get_site_host` returns
``None`` and the ``publish_content`` tool reports the capability is unsupported.

Selection is driven by ``settings.site_host`` (env ``ABOS_SITE_HOST``):

- ``none`` (default) — :func:`get_site_host` returns ``None``.
- ``cloudflare`` — Cloudflare Pages (Direct Upload), credential-gated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class HostedSite:
    """The result of publishing a page to a static host."""

    url: str  # live URL, e.g. https://abos-xxxx.pages.dev
    provider: str  # which host served it (e.g. "cloudflare")
    project: str  # the host-side project the deployment belongs to
    deployment_id: str  # opaque vendor deployment reference


class SiteHostError(RuntimeError):
    """Raised when publishing / attaching a domain fails (vendor error, no creds)."""


@runtime_checkable
class SiteHost(Protocol):
    async def publish(self, *, slug: str, title: str, html: str) -> HostedSite:
        """Publish ``html`` as a single-page site and return its live URL."""
        ...

    async def attach_domain(self, *, project: str, domain: str) -> str:
        """Attach ``domain`` to ``project`` on the host. Returns a status string."""
        ...

    async def domain_status(self, *, project: str, domain: str) -> str:
        """Return the host's current status for ``domain`` (e.g. "active")."""
        ...


def get_site_host(name: str | None = None) -> SiteHost | None:
    """Return the configured site host, or ``None`` if none is wired.

    ``name`` overrides ``settings.site_host`` when given. Unknown names raise
    ``ValueError`` so a misconfiguration fails loudly rather than silently doing
    nothing.
    """
    from app.config import settings

    key = (name or settings.site_host).strip().lower()
    if key == "none":
        return None
    if key == "cloudflare":
        from app.integrations.cloudflare import CloudflareSiteHost

        return CloudflareSiteHost()
    raise ValueError(f"unknown site host: {key!r}")
