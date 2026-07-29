"""The S3-compatible file store (Cloudflare R2) and the platform-managed default.

Three network-free layers: the SigV4 signer against AWS's published test vector
(the crypto is the part most likely to be subtly wrong), the provider's request
construction / XML parsing via a mocked transport, and the resolver falling back
to the managed store only when no founder-owned store is connected.
"""

from __future__ import annotations

import hashlib
import uuid

import httpx

from app.config import settings
from app.integrations.files import FileProviderError
from app.integrations.s3 import _EMPTY_SHA256, S3FileProvider, _sigv4_signature
from app.services import integrations as integrations_svc


def test_sigv4_matches_aws_get_vanilla_vector():
    """Our signer reproduces the AWS SigV4 test-suite `get-vanilla` signature."""
    signature, signed_headers = _sigv4_signature(
        secret_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        region="us-east-1",
        service="service",
        amzdate="20150830T123600Z",
        datestamp="20150830",
        method="GET",
        canonical_uri="/",
        canonical_querystring="",
        headers_to_sign={"host": "example.amazonaws.com", "x-amz-date": "20150830T123600Z"},
        payload_hash=_EMPTY_SHA256,
    )
    assert signed_headers == "host;x-amz-date"
    assert signature == "5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"


_LIST_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
    "<Name>bkt</Name><Prefix>companies/x/.galaxia/Acme/Reports/</Prefix>"
    "<Contents><Key>companies/x/.galaxia/Acme/Reports/q3.md</Key><Size>12</Size></Contents>"
    "<Contents><Key>companies/x/.galaxia/Acme/Reports/</Key><Size>0</Size></Contents>"
    "<CommonPrefixes><Prefix>companies/x/.galaxia/Acme/Reports/sub/</Prefix></CommonPrefixes>"
    "</ListBucketResult>"
)


def _provider_with_recorder():
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if request.method == "PUT":
            return httpx.Response(200, text="")
        query = request.url.query.decode()
        if request.method == "GET" and "list-type" in query:
            return httpx.Response(200, text=_LIST_XML)
        if request.method == "GET":
            return httpx.Response(200, content=b"hello-bytes")
        return httpx.Response(400, text="unexpected")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = S3FileProvider(
        account_id="acct123",
        access_key_id="AKID",
        secret_access_key="SECRET",
        bucket="bkt",
        root_prefix="companies/x/",
        client=client,
    )
    return provider, recorded


async def test_upload_list_download_roundtrip():
    provider, recorded = _provider_with_recorder()

    folder = await provider.ensure_folder([".galaxia", "Acme", "Reports"])
    assert folder.folder_id == "companies/x/.galaxia/Acme/Reports/"  # id-prefixed, trailing slash

    stored = await provider.upload_file(
        folder_id=folder.folder_id, name="q3.md", content=b"data", mime_type="text/markdown"
    )
    assert stored.file_id == "companies/x/.galaxia/Acme/Reports/q3.md"
    put = recorded[-1]
    assert put.method == "PUT"
    assert put.url.path == "/bkt/companies/x/.galaxia/Acme/Reports/q3.md"
    # The body is signed: the content hash header must match the payload.
    assert put.headers["x-amz-content-sha256"] == hashlib.sha256(b"data").hexdigest()
    assert put.headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKID/")

    # list_folder returns only real files — the folder marker + CommonPrefixes are dropped.
    files = await provider.list_folder(folder.folder_id)
    assert [(f.name, f.size_bytes) for f in files] == [("q3.md", 12)]

    body = await provider.download_file(stored.file_id)
    assert body == b"hello-bytes"


async def test_auth_failure_is_typed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="<Error><Code>AccessDenied</Code></Error>")

    provider = S3FileProvider(
        account_id="a",
        access_key_id="AK",
        secret_access_key="SK",
        bucket="b",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        await provider.check_access()
        raise AssertionError("expected an auth error")
    except FileProviderError as exc:  # FileProviderAuthError is a subclass
        assert "403" in str(exc)


async def test_managed_store_configured_needs_all_four(monkeypatch):
    for attr in ("r2_account_id", "r2_access_key_id", "r2_secret_access_key", "r2_bucket"):
        monkeypatch.setattr(settings, attr, "")
    assert integrations_svc.managed_store_configured() is False
    assert integrations_svc.managed_store_provider(uuid.uuid4()) is None

    monkeypatch.setattr(settings, "r2_account_id", "acct")
    monkeypatch.setattr(settings, "r2_access_key_id", "AK")
    monkeypatch.setattr(settings, "r2_secret_access_key", "SK")
    monkeypatch.setattr(settings, "r2_bucket", "bkt")
    assert integrations_svc.managed_store_configured() is True
    cid = uuid.uuid4()
    provider = integrations_svc.managed_store_provider(cid)
    assert isinstance(provider, S3FileProvider)
    # Company isolation is by id-prefix, so a shared bucket can't cross tenants.
    folder = await provider.ensure_folder([])
    assert folder.folder_id == f"companies/{cid}/"


async def test_resolver_falls_back_to_managed_only_without_founder_store(monkeypatch):
    """A founder-owned Drive wins; the managed default is the fallback, not an override."""
    from app.services import user_drive

    async def _none(*args, **kwargs):
        return None

    monkeypatch.setattr(integrations_svc, "get_google_drive", _none)
    monkeypatch.setattr(user_drive, "get_user_drive_for_company", _none)
    monkeypatch.setattr(integrations_svc, "_owner_google_drive", _none)
    monkeypatch.setattr(settings, "r2_account_id", "acct")
    monkeypatch.setattr(settings, "r2_access_key_id", "AK")
    monkeypatch.setattr(settings, "r2_secret_access_key", "SK")
    monkeypatch.setattr(settings, "r2_bucket", "bkt")

    provider = await integrations_svc.resolve_file_provider(db=None, company_id=uuid.uuid4())
    assert isinstance(provider, S3FileProvider)

    # With the managed store cleared and still no founder store, it resolves to None.
    monkeypatch.setattr(settings, "r2_bucket", "")
    assert await integrations_svc.resolve_file_provider(db=None, company_id=uuid.uuid4()) is None
