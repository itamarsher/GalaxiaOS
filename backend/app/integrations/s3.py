"""S3-compatible :class:`~app.integrations.files.FileProvider`.

The second file-store adapter after Google Drive. It speaks the S3 REST API with
hand-rolled AWS Signature V4 (no boto dependency — just ``httpx`` + ``hashlib``),
so it works against any S3-compatible endpoint. The motivating target is
**Cloudflare R2** (10 GB free tier, endpoint ``https://<account>.r2.cloudflarestorage.com``),
which is what powers the platform's *managed default store*: one platform-owned
bucket, each company isolated under its own ``root_prefix`` (``companies/<id>/``),
so a founder gets a working file store at launch with zero setup of their own.

S3 has no real folders — a "folder" is just a key prefix — so :meth:`ensure_folder`
is a pure path computation (no network round-trip), and files are objects whose key
is ``<prefix>/<name>``. A same-named upload overwrites in place, matching the
provider contract's single-source-of-truth semantics.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import quote
from xml.etree import ElementTree

import httpx

from app.integrations.files import (
    FileProviderAuthError,
    FileProviderError,
    FolderRef,
    StoredFile,
)

_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_ALGORITHM = "AWS4-HMAC-SHA256"


def _signing_key(secret_key: str, datestamp: str, region: str, service: str) -> bytes:
    k_date = hmac.new(("AWS4" + secret_key).encode(), datestamp.encode(), hashlib.sha256).digest()
    k_region = hmac.new(k_date, region.encode(), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service.encode(), hashlib.sha256).digest()
    return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()


def _sigv4_signature(
    *,
    secret_key: str,
    region: str,
    service: str,
    amzdate: str,
    datestamp: str,
    method: str,
    canonical_uri: str,
    canonical_querystring: str,
    headers_to_sign: dict[str, str],
    payload_hash: str,
) -> tuple[str, str]:
    """Return ``(signature_hex, signed_headers)`` for one SigV4 request.

    Factored out of the transport so it can be unit-tested against AWS's published
    SigV4 test vectors without any network — the crypto is the part most likely to
    be subtly wrong, so it is exercised directly.
    """
    signed_headers = ";".join(sorted(headers_to_sign))
    canonical_headers = "".join(f"{k}:{headers_to_sign[k]}\n" for k in sorted(headers_to_sign))
    canonical_request = "\n".join(
        [method, canonical_uri, canonical_querystring, canonical_headers, signed_headers, payload_hash]
    )
    scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [_ALGORITHM, amzdate, scope, hashlib.sha256(canonical_request.encode()).hexdigest()]
    )
    signature = hmac.new(
        _signing_key(secret_key, datestamp, region, service),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()
    return signature, signed_headers


def _canonical_query(params: dict[str, str]) -> str:
    return "&".join(
        f"{quote(k, safe='-_.~')}={quote(str(v), safe='-_.~')}" for k, v in sorted(params.items())
    )


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class S3FileProvider:
    """A file store backed by any S3-compatible endpoint (default: Cloudflare R2)."""

    def __init__(
        self,
        *,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        root_prefix: str = "",
        endpoint: str | None = None,
        region: str = "auto",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._bucket = bucket
        # Normalise the prefix to end with a single "/" (or be empty).
        self._root = (root_prefix.strip("/") + "/") if root_prefix.strip("/") else ""
        self._region = region
        self._endpoint = (endpoint or f"https://{account_id}.r2.cloudflarestorage.com").rstrip("/")
        self._host = self._endpoint.split("://", 1)[-1]
        self._client = client

    # ── signing / transport ────────────────────────────────────────────────
    def _authorized_headers(
        self, *, method: str, canonical_uri: str, query: dict[str, str], payload: bytes
    ) -> dict[str, str]:
        now = datetime.now(timezone.utc)
        amzdate = now.strftime("%Y%m%dT%H%M%SZ")
        datestamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(payload).hexdigest() if payload else _EMPTY_SHA256
        to_sign = {
            "host": self._host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amzdate,
        }
        signature, signed_headers = _sigv4_signature(
            secret_key=self._secret_access_key,
            region=self._region,
            service="s3",
            amzdate=amzdate,
            datestamp=datestamp,
            method=method,
            canonical_uri=canonical_uri,
            canonical_querystring=_canonical_query(query),
            headers_to_sign=to_sign,
            payload_hash=payload_hash,
        )
        scope = f"{datestamp}/{self._region}/s3/aws4_request"
        return {
            "x-amz-date": amzdate,
            "x-amz-content-sha256": payload_hash,
            "Authorization": (
                f"{_ALGORITHM} Credential={self._access_key_id}/{scope}, "
                f"SignedHeaders={signed_headers}, Signature={signature}"
            ),
        }

    def _key_uri(self, key: str) -> str:
        # Path-style: /<bucket>/<key>, each segment encoded but "/" preserved.
        return f"/{quote(self._bucket, safe='')}/{quote(key, safe='/-_.~')}"

    async def _send(
        self,
        *,
        method: str,
        canonical_uri: str,
        query: dict[str, str] | None = None,
        payload: bytes = b"",
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        query = query or {}
        headers = self._authorized_headers(
            method=method, canonical_uri=canonical_uri, query=query, payload=payload
        )
        if extra_headers:
            headers.update(extra_headers)
        url = f"{self._endpoint}{canonical_uri}"
        if query:
            url = f"{url}?{_canonical_query(query)}"
        try:
            if self._client is not None:
                resp = await self._client.request(method, url, headers=headers, content=payload)
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.request(method, url, headers=headers, content=payload)
        except httpx.HTTPError as exc:
            raise FileProviderError(f"S3 request failed: {exc}") from exc
        if resp.status_code in (401, 403):
            raise FileProviderAuthError(
                f"S3 credentials rejected ({resp.status_code}): {resp.text[:200]}"
            )
        if resp.status_code >= 300:
            raise FileProviderError(f"S3 {method} failed ({resp.status_code}): {resp.text[:200]}")
        return resp

    # ── FileProvider contract ───────────────────────────────────────────────
    async def ensure_folder(self, path: list[str]) -> FolderRef:
        # No network: an S3 "folder" is just a key prefix, created implicitly on upload.
        clean = [seg.strip("/") for seg in path if seg.strip("/")]
        folder_id = self._root + ("/".join(clean) + "/" if clean else "")
        return FolderRef(folder_id=folder_id, path="/".join(clean))

    async def upload_file(
        self, *, folder_id: str, name: str, content: bytes, mime_type: str
    ) -> StoredFile:
        key = f"{folder_id}{name}"
        await self._send(
            method="PUT",
            canonical_uri=self._key_uri(key),
            payload=content,
            extra_headers={"Content-Type": mime_type or "application/octet-stream"},
        )
        return StoredFile(
            file_id=key, name=name, mime_type=mime_type, web_url=None, size_bytes=len(content)
        )

    async def list_folder(self, folder_id: str) -> list[StoredFile]:
        resp = await self._send(
            method="GET",
            canonical_uri=f"/{quote(self._bucket, safe='')}",
            query={"list-type": "2", "prefix": folder_id, "delimiter": "/", "max-keys": "1000"},
        )
        try:
            root = ElementTree.fromstring(resp.text)
        except ElementTree.ParseError as exc:
            raise FileProviderError(f"S3 list returned unparseable XML: {exc}") from exc
        out: list[StoredFile] = []
        for contents in root:
            if _localname(contents.tag) != "Contents":
                continue
            key = size = None
            for child in contents:
                if _localname(child.tag) == "Key":
                    key = child.text
                elif _localname(child.tag) == "Size":
                    size = child.text
            if not key:
                continue
            name = key[len(folder_id):] if key.startswith(folder_id) else key
            if not name or name.endswith("/"):
                continue  # the folder marker itself, not a file
            out.append(
                StoredFile(
                    file_id=key,
                    name=name,
                    mime_type="application/octet-stream",
                    web_url=None,
                    size_bytes=int(size) if size and size.isdigit() else None,
                )
            )
        return out

    async def download_file(self, file_id: str) -> bytes:
        resp = await self._send(method="GET", canonical_uri=self._key_uri(file_id))
        return resp.content

    async def check_access(self) -> None:
        """Prove the credentials + bucket are reachable (a 1-key list). Raises
        :class:`FileProviderError` / :class:`FileProviderAuthError` on failure."""
        await self._send(
            method="GET",
            canonical_uri=f"/{quote(self._bucket, safe='')}",
            query={"list-type": "2", "max-keys": "1"},
        )
