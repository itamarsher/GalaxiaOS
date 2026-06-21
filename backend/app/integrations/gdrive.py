"""Google Drive adapter — REAL file storage in the founder's personal Drive.

Implements the :class:`~app.integrations.files.FileProvider` seam against the
Drive v3 REST API. Authentication is **per-company, bring-your-own** OAuth: the
founder connects their own Google account (Settings), and ABOS stores the
resulting ``client_id`` / ``client_secret`` / ``refresh_token`` envelope-encrypted
(same store as every other BYO secret). At call time the refresh token is
exchanged for a short-lived access token (cached until it nears expiry), so files
are written into the founder's own ``My Drive`` under ``.abos/<company>/…`` and
remain theirs — readable, auditable, and exportable for due diligence without ABOS
in the loop.

There is deliberately no simulated Drive: without credentials
:func:`~app.services.integrations.resolve_file_provider` returns ``None`` and the
file tools report the capability is unsupported, so an agent never assumes a
document was filed when it wasn't.

All network shaping is done by pure, unit-testable helpers (``_token_form``,
``_parse_token``, ``_child_query``, ``_parse_file``, ``_multipart_related``) so
request/response mapping is covered offline without hitting Google.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx

from app.config import settings
from app.integrations.files import FileProviderError, FolderRef, StoredFile

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DRIVE_API = "https://www.googleapis.com/drive/v3/files"
_DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
_FOLDER_MIME = "application/vnd.google-apps.folder"
# Fields we read back for a file/folder (kept in one place so list + create agree).
_FILE_FIELDS = "id,name,mimeType,webViewLink,size"


def _escape_query_value(value: str) -> str:
    """Escape a value for a Drive ``q`` string literal (backslash + single quote)."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


class GoogleDriveFileProvider:
    """Real Google Drive file store (credential-gated, OAuth refresh-token)."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        root_folder_id: str = "root",
        timeout: float | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        # "root" is Drive's alias for the My Drive root; a folder id pins storage
        # elsewhere (e.g. a Shared Drive) without changing any calling code.
        self._root_folder_id = root_folder_id or "root"
        self._timeout = timeout if timeout is not None else settings.web_search_timeout_seconds
        self._access_token: str | None = None
        self._token_expiry: float = 0.0

    # ───────────────────────────── auth ─────────────────────────────

    def _token_form(self) -> dict[str, str]:
        return {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": self._refresh_token,
            "grant_type": "refresh_token",
        }

    @staticmethod
    def _parse_token(status_code: int, body: dict) -> tuple[str, int]:
        """Map Google's token response to ``(access_token, expires_in_seconds)``."""
        if status_code >= 400 or "access_token" not in body:
            detail = body.get("error_description") or body.get("error") or f"HTTP {status_code}"
            raise FileProviderError(f"Google token refresh failed: {detail}")
        return str(body["access_token"]), int(body.get("expires_in", 3600))

    async def _access(self) -> str:
        """Return a valid access token, refreshing when missing or near expiry."""
        # Refresh ~60s early so a token never expires mid-request.
        if self._access_token and time.monotonic() < self._token_expiry - 60:
            return self._access_token
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(_TOKEN_URL, data=self._token_form())
                data = resp.json() if resp.content else {}
        except httpx.HTTPError as exc:
            raise FileProviderError(f"Google token request failed: {exc}") from exc
        except ValueError as exc:
            raise FileProviderError(f"Google token returned non-JSON: {exc}") from exc
        token, expires_in = self._parse_token(resp.status_code, data)
        self._access_token = token
        self._token_expiry = time.monotonic() + expires_in
        return token

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._access()}"}

    # ──────────────────────────── helpers ────────────────────────────

    @staticmethod
    def _child_query(parent_id: str, name: str, *, folder: bool | None = None) -> str:
        """Drive ``q`` to find a non-trashed child named ``name`` under ``parent_id``."""
        q = (
            f"'{_escape_query_value(parent_id)}' in parents "
            f"and name = '{_escape_query_value(name)}' "
            "and trashed = false"
        )
        if folder is True:
            q += f" and mimeType = '{_FOLDER_MIME}'"
        elif folder is False:
            q += f" and mimeType != '{_FOLDER_MIME}'"
        return q

    @staticmethod
    def _parse_file(data: dict[str, Any]) -> StoredFile:
        raw_size = data.get("size")
        return StoredFile(
            file_id=str(data["id"]),
            name=str(data.get("name", "")),
            mime_type=str(data.get("mimeType", "application/octet-stream")),
            web_url=data.get("webViewLink"),
            size_bytes=int(raw_size) if raw_size is not None else None,
        )

    @staticmethod
    def _multipart_related(metadata: dict, content: bytes, mime_type: str) -> tuple[str, bytes]:
        """Build a Drive ``multipart/related`` upload body (metadata part + media part)."""
        boundary = f"abos_{uuid.uuid4().hex}"
        meta = json.dumps(metadata).encode("utf-8")
        body = b"".join(
            [
                f"--{boundary}\r\n".encode(),
                b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
                meta,
                b"\r\n",
                f"--{boundary}\r\n".encode(),
                f"Content-Type: {mime_type}\r\n\r\n".encode(),
                content,
                b"\r\n",
                f"--{boundary}--".encode(),
            ]
        )
        return f"multipart/related; boundary={boundary}", body

    async def _get_json(self, client: httpx.AsyncClient, url: str, **kwargs) -> dict:
        try:
            resp = await client.get(url, headers=await self._headers(), **kwargs)
            data = resp.json() if resp.content else {}
        except httpx.HTTPError as exc:
            raise FileProviderError(f"Drive request failed: {exc}") from exc
        except ValueError as exc:
            raise FileProviderError(f"Drive returned non-JSON: {exc}") from exc
        if resp.status_code >= 400:
            raise FileProviderError(f"Drive error {resp.status_code}: {self._err(data)}")
        return data

    @staticmethod
    def _err(body: dict) -> str:
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err)
        return str(err or body)

    async def _find_child(
        self, client: httpx.AsyncClient, parent_id: str, name: str, *, folder: bool | None = None
    ) -> dict | None:
        data = await self._get_json(
            client,
            _DRIVE_API,
            params={
                "q": self._child_query(parent_id, name, folder=folder),
                "fields": f"files({_FILE_FIELDS})",
                "spaces": "drive",
                "pageSize": 1,
            },
        )
        files = data.get("files") or []
        return files[0] if files else None

    async def _create_folder(self, client: httpx.AsyncClient, parent_id: str, name: str) -> dict:
        try:
            resp = await client.post(
                _DRIVE_API,
                headers={**await self._headers(), "Content-Type": "application/json"},
                params={"fields": _FILE_FIELDS},
                json={"name": name, "mimeType": _FOLDER_MIME, "parents": [parent_id]},
            )
            data = resp.json() if resp.content else {}
        except httpx.HTTPError as exc:
            raise FileProviderError(f"Drive create-folder failed: {exc}") from exc
        if resp.status_code >= 400:
            raise FileProviderError(f"Drive create-folder error: {self._err(data)}")
        return data

    # ─────────────────────────── FileProvider ───────────────────────────

    async def ensure_folder(self, path: list[str]) -> FolderRef:
        parent = self._root_folder_id
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for segment in path:
                name = segment.strip()
                if not name:
                    continue
                existing = await self._find_child(client, parent, name, folder=True)
                node = existing or await self._create_folder(client, parent, name)
                parent = str(node["id"])
        return FolderRef(folder_id=parent, path="/".join(s.strip() for s in path if s.strip()))

    async def upload_file(
        self, *, folder_id: str, name: str, content: bytes, mime_type: str
    ) -> StoredFile:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            existing = await self._find_child(client, folder_id, name, folder=False)
            try:
                if existing:
                    # Replace the media of the existing file so the doc updates in
                    # place (one durable id per named document).
                    resp = await client.patch(
                        f"{_DRIVE_UPLOAD}/{existing['id']}",
                        headers={**await self._headers(), "Content-Type": mime_type},
                        params={"uploadType": "media", "fields": _FILE_FIELDS},
                        content=content,
                    )
                else:
                    ctype, body = self._multipart_related(
                        {"name": name, "parents": [folder_id]}, content, mime_type
                    )
                    resp = await client.post(
                        _DRIVE_UPLOAD,
                        headers={**await self._headers(), "Content-Type": ctype},
                        params={"uploadType": "multipart", "fields": _FILE_FIELDS},
                        content=body,
                    )
                data = resp.json() if resp.content else {}
            except httpx.HTTPError as exc:
                raise FileProviderError(f"Drive upload failed: {exc}") from exc
            if resp.status_code >= 400:
                raise FileProviderError(f"Drive upload error: {self._err(data)}")
        return self._parse_file(data)

    async def list_folder(self, folder_id: str) -> list[StoredFile]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            data = await self._get_json(
                client,
                _DRIVE_API,
                params={
                    "q": (
                        f"'{_escape_query_value(folder_id)}' in parents "
                        "and trashed = false "
                        f"and mimeType != '{_FOLDER_MIME}'"
                    ),
                    "fields": f"files({_FILE_FIELDS})",
                    "spaces": "drive",
                    "orderBy": "name",
                },
            )
        return [self._parse_file(f) for f in (data.get("files") or [])]

    async def download_file(self, file_id: str) -> bytes:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.get(
                    f"{_DRIVE_API}/{file_id}",
                    headers=await self._headers(),
                    params={"alt": "media"},
                )
            except httpx.HTTPError as exc:
                raise FileProviderError(f"Drive download failed: {exc}") from exc
            if resp.status_code >= 400:
                detail = resp.json() if resp.content else {}
                raise FileProviderError(f"Drive download error: {self._err(detail)}")
            return resp.content
