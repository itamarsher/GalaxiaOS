"""Render deployment observability — a read-only view of our own deploys.

Lets GalaxiaOS's agents see what's happening with the platform's Render services
and deploys (is the last deploy live? did it fail? which commit?). Credential-
gated by a Render API key: GalaxiaOS owns the dogfooding Render account, so the
key is global (``ABOS_RENDER_API_KEY``); a company may also connect its own via a
BYOK ``render`` key. Without a key the client is unavailable and the ``render_*``
tools report they are not connected — they never fabricate a status.

Read-only: only GET endpoints of the Render API (v1) are used. Response parsing is
in pure staticmethods so it is unit-testable offline with a mock transport.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import settings

# Owner ids resolved from an API key, cached so we look them up from the key at
# most once per process (keyed by the key itself, since a key maps to one owner).
_OWNER_ID_CACHE: dict[str, str] = {}


class RenderError(RuntimeError):
    """Raised when a Render API call fails (missing key, API error)."""


@dataclass(frozen=True)
class RenderService:
    id: str
    name: str
    type: str
    suspended: str
    dashboard_url: str


@dataclass(frozen=True)
class RenderDeploy:
    id: str
    status: str
    commit_id: str
    commit_message: str
    created_at: str
    finished_at: str


@dataclass(frozen=True)
class RenderLogEntry:
    timestamp: str
    message: str


@dataclass(frozen=True)
class RenderOwner:
    id: str
    name: str
    email: str
    type: str


class RenderClient:
    """Read-only Render API v1 client (credential-gated)."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        owner_id: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._key = api_key if api_key is not None else settings.render_api_key
        self._base = (base_url or settings.render_api_base_url).rstrip("/")
        self._owner_id = owner_id if owner_id is not None else settings.render_owner_id
        self._timeout = timeout if timeout is not None else settings.web_search_timeout_seconds
        # Test seam: inject a MockTransport to exercise the API dance offline.
        self._transport = transport

    def _require_key(self) -> str:
        if not self._key:
            raise RenderError("Render API key missing (set ABOS_RENDER_API_KEY).")
        return self._key

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._require_key()}", "Accept": "application/json"}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    async def _get(self, path: str, params: dict | None = None) -> object:
        headers = self._headers()
        try:
            async with self._client() as client:
                resp = await client.get(f"{self._base}{path}", params=params, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            raise RenderError(self._explain_status(exc)) from exc
        except httpx.HTTPError as exc:
            raise RenderError(f"Render request failed: {exc}") from exc
        except ValueError as exc:  # non-JSON body
            raise RenderError(f"Render returned non-JSON: {exc}") from exc

    async def list_services(self, *, limit: int = 20) -> list[RenderService]:
        data = await self._get("/services", {"limit": max(1, limit)})
        items = data if isinstance(data, list) else []
        return [self._parse_service(_unwrap(item, "service")) for item in items]

    async def list_deploys(self, service_id: str, *, limit: int = 10) -> list[RenderDeploy]:
        data = await self._get(f"/services/{service_id}/deploys", {"limit": max(1, limit)})
        items = data if isinstance(data, list) else []
        return [self._parse_deploy(_unwrap(item, "deploy")) for item in items]

    async def get_deploy(self, service_id: str, deploy_id: str) -> RenderDeploy:
        data = await self._get(f"/services/{service_id}/deploys/{deploy_id}")
        return self._parse_deploy(_unwrap(data, "deploy"))

    async def list_owners(self) -> list[RenderOwner]:
        """The owners (teams/personal account) this API key can see."""
        data = await self._get("/owners")
        items = data if isinstance(data, list) else []
        return [self._parse_owner(_unwrap(item, "owner")) for item in items]

    async def resolve_owner_id(self) -> str:
        """Return the owner id for owner-scoped calls (the logs API).

        Uses the explicit ``render_owner_id`` when set; otherwise derives it from
        the API key via ``GET /v1/owners`` and caches it — so ``ABOS_RENDER_OWNER_ID``
        is optional. Raises :class:`RenderError` when the key maps to zero owners,
        or to several (ambiguous — set the env var to pick one).
        """
        if self._owner_id:
            return self._owner_id
        key = self._require_key()
        cached = _OWNER_ID_CACHE.get(key)
        if cached:
            return cached
        owners = await self.list_owners()
        if not owners:
            raise RenderError("Render API key maps to no owners; cannot resolve an owner id.")
        if len(owners) > 1:
            raise RenderError(
                "Render API key can see multiple owners — set ABOS_RENDER_OWNER_ID to one of: "
                + ", ".join(f"{o.name}={o.id}" for o in owners)
            )
        _OWNER_ID_CACHE[key] = owners[0].id
        return owners[0].id

    async def get_logs(self, resource_id: str, *, limit: int = 50) -> list[RenderLogEntry]:
        """Recent log lines for a Render resource (service id), newest last.

        Uses GET /v1/logs, which is owner-scoped. The owner id is resolved from the
        API key automatically (see :meth:`resolve_owner_id`), so no separate owner
        setting is required; :class:`RenderError` is raised only if it can't be
        determined (no owners, or an ambiguous multi-owner key).
        """
        owner_id = await self.resolve_owner_id()
        data = await self._get(
            "/logs",
            {"ownerId": owner_id, "resource": resource_id, "limit": max(1, limit)},
        )
        rows = data.get("logs") if isinstance(data, dict) else None
        return [self._parse_log(r) for r in (rows or []) if isinstance(r, dict)]

    @staticmethod
    def _parse_owner(d: dict) -> RenderOwner:
        return RenderOwner(
            id=str(d.get("id") or ""),
            name=str(d.get("name") or ""),
            email=str(d.get("email") or ""),
            type=str(d.get("type") or ""),
        )

    @staticmethod
    def _parse_log(d: dict) -> RenderLogEntry:
        return RenderLogEntry(
            timestamp=str(d.get("timestamp") or ""),
            message=" ".join(str(d.get("message") or "").split()),
        )

    @staticmethod
    def _explain_status(exc: httpx.HTTPStatusError) -> str:
        status = exc.response.status_code
        if status == 401:
            return "Render rejected the token (401): it is set but invalid/expired."
        if status == 403:
            return "Render denied the request (403): the token lacks permission or is rate-limited."
        if status == 404:
            return "Render returned 404: the service/deploy id was not found for this token."
        return f"Render request failed ({status}): {exc}"

    @staticmethod
    def _parse_service(d: dict) -> RenderService:
        return RenderService(
            id=str(d.get("id") or ""),
            name=str(d.get("name") or ""),
            type=str(d.get("type") or ""),
            suspended=str(d.get("suspended") or ""),
            dashboard_url=str(d.get("dashboardUrl") or ""),
        )

    @staticmethod
    def _parse_deploy(d: dict) -> RenderDeploy:
        commit = d.get("commit") or {}
        return RenderDeploy(
            id=str(d.get("id") or ""),
            status=str(d.get("status") or ""),
            commit_id=str(commit.get("id") or "")[:12],
            commit_message=" ".join(str(commit.get("message") or "").split())[:140],
            created_at=str(d.get("createdAt") or ""),
            finished_at=str(d.get("finishedAt") or ""),
        )


def _unwrap(item: object, key: str) -> dict:
    """Render list endpoints wrap each row as ``{"<key>": {...}, "cursor": ...}``.

    Unwrap that envelope when present; tolerate a bare object too.
    """
    if isinstance(item, dict):
        inner = item.get(key)
        if isinstance(inner, dict):
            return inner
        return item
    return {}


def get_render_client() -> RenderClient | None:
    """The global (dogfooding-account) Render client, or ``None`` if no key is set."""
    return RenderClient() if settings.render_api_key.strip() else None
