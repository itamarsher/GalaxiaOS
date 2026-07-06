"""Site-hosting seam — where a generated landing page actually gets served.

A :class:`SiteHost` publishes a single HTML page to a real static host and can
attach a custom domain to it. Like the registrar seam there is deliberately NO
simulated host: fabricating a "published" URL lets agents believe a page went live
when it did not.

Hosting is bring-your-own-key: the runtime entry point is
:func:`app.services.integrations.resolve_site_host`, which builds a per-company
adapter only when that company has saved credentials. :func:`get_site_host` is a
plain name→adapter selector (``cloudflare`` by default; ``none`` → ``None``).
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
    """Construct a site host by name (no credentials; the resolver supplies those).

    ``cloudflare`` (the default) → a :class:`CloudflareSiteHost`; ``none`` → ``None``;
    anything else raises ``ValueError`` so a typo fails loudly.
    """
    key = (name or "cloudflare").strip().lower()
    if key == "none":
        return None
    if key == "cloudflare":
        from app.integrations.cloudflare import CloudflareSiteHost

        return CloudflareSiteHost()
    raise ValueError(f"unknown site host: {key!r}")
