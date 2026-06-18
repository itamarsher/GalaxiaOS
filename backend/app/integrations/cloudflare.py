"""Cloudflare adapter — Pages hosting + DNS, credential-gated (REAL side effects).

One vendor backs both new seams:

- :class:`CloudflareSiteHost` implements :class:`~app.integrations.sitehost.SiteHost`
  using **Cloudflare Pages** (Direct Upload): create/look up a project, deploy a
  single ``index.html``, attach a custom domain.
- :class:`CloudflareDns` implements :class:`~app.integrations.dns.DnsProvider` using
  **Cloudflare DNS**: create/look up the zone (returning nameservers to delegate),
  report activation, and upsert records.

Credentials come from settings (``ABOS_CLOUDFLARE_API_TOKEN`` /
``ABOS_CLOUDFLARE_ACCOUNT_ID``); without them every method raises rather than
attempting a no-op. The token needs **Pages:Edit**, **DNS:Edit**, **Zone:Edit**.

⚠️  These perform REAL changes on a live Cloudflare account and have not been
exercised against the live API in this repo. Both seams default to ``none``
(disabled); verify against a throwaway account/domain before enabling.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from app.config import settings
from app.integrations.dns import DnsError, Zone
from app.integrations.sitehost import HostedSite, SiteHostError

_API = "https://api.cloudflare.com/client/v4"
_TIMEOUT = 30.0


def _require_token(error: type[Exception] = SiteHostError) -> str:
    if not settings.cloudflare_api_token:
        raise error("Cloudflare credentials missing: set ABOS_CLOUDFLARE_API_TOKEN.")
    return settings.cloudflare_api_token


def _require_account(error: type[Exception] = SiteHostError) -> str:
    if not settings.cloudflare_account_id:
        raise error("Cloudflare account missing: set ABOS_CLOUDFLARE_ACCOUNT_ID.")
    return settings.cloudflare_account_id


async def _request(
    method: str,
    path: str,
    *,
    error: type[Exception],
    json: dict | None = None,
    data: dict | None = None,
    files: dict | None = None,
    token: str | None = None,
    expected: tuple[int, ...] = (200,),
) -> dict[str, Any]:
    """Call the Cloudflare API and return the ``result`` payload.

    Cloudflare wraps every response in ``{success, errors, result}``; a non-2xx or
    ``success: false`` is surfaced as ``error`` with the joined messages.
    """
    headers = {"Authorization": f"Bearer {token or _require_token(error)}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.request(
                method, f"{_API}{path}", headers=headers, json=json, data=data, files=files
            )
    except httpx.HTTPError as exc:
        raise error(f"Cloudflare request failed: {exc}") from exc

    try:
        body = resp.json()
    except ValueError as exc:
        raise error(f"Cloudflare returned non-JSON ({resp.status_code})") from exc

    if resp.status_code not in expected or not body.get("success", False):
        msgs = "; ".join(str(e.get("message", e)) for e in body.get("errors") or []) or resp.text
        raise error(f"Cloudflare error ({resp.status_code}): {msgs}")
    return body.get("result") or {}


class CloudflareSiteHost:
    """Cloudflare Pages site host (Direct Upload of a single HTML page)."""

    async def publish(self, *, slug: str, title: str, html: str) -> HostedSite:
        account = _require_account()
        token = _require_token()
        project = _project_name(slug)
        await self._ensure_project(account, project, token)
        deployment_id = await self._deploy_index_html(account, project, html, token)
        return HostedSite(
            url=f"https://{project}.pages.dev",
            provider="cloudflare",
            project=project,
            deployment_id=deployment_id,
        )

    async def attach_domain(self, *, project: str, domain: str) -> str:
        account = _require_account()
        result = await _request(
            "POST",
            f"/accounts/{account}/pages/projects/{project}/domains",
            json={"name": domain},
            error=SiteHostError,
            expected=(200, 201),
        )
        return str(result.get("status") or "attaching")

    async def domain_status(self, *, project: str, domain: str) -> str:
        account = _require_account()
        result = await _request(
            "GET",
            f"/accounts/{account}/pages/projects/{project}/domains/{domain}",
            error=SiteHostError,
        )
        return str(result.get("status") or "unknown")

    async def _ensure_project(self, account: str, project: str, token: str) -> None:
        """Create the Pages project if it does not already exist (idempotent)."""
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{_API}/accounts/{account}/pages/projects/{project}"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise SiteHostError(f"Cloudflare request failed: {exc}") from exc
        if resp.status_code == 200 and resp.json().get("success"):
            return
        await _request(
            "POST",
            f"/accounts/{account}/pages/projects",
            json={"name": project, "production_branch": "main"},
            error=SiteHostError,
            token=token,
            expected=(200, 201),
        )

    async def _deploy_index_html(
        self, account: str, project: str, html: str, token: str
    ) -> str:
        """Direct-upload a single ``index.html`` and create a production deployment.

        Cloudflare's Direct Upload flow: fetch a short-lived upload JWT, hash the
        asset, register it, upload its base64 payload, then create the deployment
        with the path->hash manifest. A landing page is one file, so the manifest
        has a single entry.
        """
        upload = await _request(
            "GET",
            f"/accounts/{account}/pages/projects/{project}/upload-token",
            error=SiteHostError,
            token=token,
        )
        jwt = upload.get("jwt")
        if not jwt:
            raise SiteHostError("Cloudflare did not return a Pages upload token.")

        content_b64 = base64.b64encode(html.encode("utf-8")).decode("ascii")
        file_hash = _asset_hash(content_b64, "html")

        # Register + upload the asset (idempotent: already-present hashes are skipped).
        missing = await _request(
            "POST",
            "/pages/assets/check-missing",
            json={"hashes": [file_hash]},
            error=SiteHostError,
            token=jwt,
        )
        if file_hash in (missing or []):
            await _request(
                "POST",
                "/pages/assets/upload",
                json=[
                    {
                        "key": file_hash,
                        "value": content_b64,
                        "metadata": {"contentType": "text/html"},
                        "base64": True,
                    }
                ],
                error=SiteHostError,
                token=jwt,
            )

        deployment = await _request(
            "POST",
            f"/accounts/{account}/pages/projects/{project}/deployments",
            data={"manifest": _json({"/index.html": file_hash})},
            error=SiteHostError,
            token=token,
            expected=(200, 201),
        )
        return str(deployment.get("id") or "")


class CloudflareDns:
    """Cloudflare DNS provider (zone + record management)."""

    async def ensure_zone(self, domain: str) -> Zone:
        account = _require_account(DnsError)
        existing = await self._find_zone(domain)
        if existing is not None:
            return existing
        result = await _request(
            "POST",
            "/zones",
            json={"name": domain, "account": {"id": account}, "type": "full"},
            error=DnsError,
            expected=(200, 201),
        )
        return _zone_from_result(result)

    async def zone_status(self, zone_id: str) -> str:
        result = await _request("GET", f"/zones/{zone_id}", error=DnsError)
        return str(result.get("status") or "unknown")

    async def upsert_record(
        self, *, zone_id: str, type: str, name: str, content: str, proxied: bool = True
    ) -> str:
        existing = await _request(
            "GET",
            f"/zones/{zone_id}/dns_records?type={type}&name={name}",
            error=DnsError,
        )
        body = {"type": type, "name": name, "content": content, "proxied": proxied}
        # ``existing`` is a list when querying with filters; reuse the first match.
        record = existing[0] if isinstance(existing, list) and existing else None
        if record:
            result = await _request(
                "PUT",
                f"/zones/{zone_id}/dns_records/{record['id']}",
                json=body,
                error=DnsError,
            )
        else:
            result = await _request(
                "POST",
                f"/zones/{zone_id}/dns_records",
                json=body,
                error=DnsError,
                expected=(200, 201),
            )
        return str(result.get("id") or "")

    async def _find_zone(self, domain: str) -> Zone | None:
        result = await _request("GET", f"/zones?name={domain}", error=DnsError)
        if isinstance(result, list) and result:
            return _zone_from_result(result[0])
        return None


# ── helpers ────────────────────────────────────────────────────────────────────


def _project_name(slug: str) -> str:
    """A DNS-safe, deterministic Pages project name (lowercase, <=58 chars)."""
    safe = "".join(c if c.isalnum() else "-" for c in slug.lower()).strip("-")
    safe = "-".join(filter(None, safe.split("-"))) or "site"
    return f"abos-{safe}"[:58].rstrip("-")


def _zone_from_result(result: dict) -> Zone:
    return Zone(
        zone_id=str(result.get("id") or ""),
        nameservers=list(result.get("name_servers") or []),
        status=str(result.get("status") or "pending"),
    )


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj)


def _asset_hash(content_b64: str, extension: str) -> str:
    """Cloudflare Pages asset hash: blake3(base64_content + extension)[:32].

    blake3 is imported lazily so the dependency is only needed when actually
    publishing to Cloudflare (the seam defaults to ``none``).
    """
    try:
        import blake3  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on optional dep
        raise SiteHostError(
            "Publishing to Cloudflare Pages requires the 'blake3' package."
        ) from exc
    digest = blake3.blake3((content_b64 + extension).encode("utf-8")).hexdigest()
    return digest[:32]
