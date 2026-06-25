"""File provider seam — DB-free coverage.

Mirrors the offline style of the other integration tests: pure parsers for the
Google Drive adapter, the folder taxonomy in the files service, the agent-tool
registration, and the archive / best-effort auto-archive paths exercised through an
in-memory :class:`FakeFileProvider` (so nothing here touches Google or Postgres).
"""

from __future__ import annotations

import uuid

import pytest

from app.config import settings
from app.integrations import gdrive_oauth
from app.integrations.files import FileProvider, FileProviderError, FolderRef, StoredFile
from app.integrations.gdrive import GoogleDriveFileProvider, _escape_query_value
from app.models.enums import FileCategory
from app.runtime.tools import TOOL_SPECS
from app.runtime.tools.files import HANDLERS, SPECS
from app.security import create_oauth_state, decode_oauth_state
from app.services import files as files_svc

# ─────────────────────────── Google Drive parsers ───────────────────────────


def test_parse_token_success():
    token, expires = GoogleDriveFileProvider._parse_token(
        200, {"access_token": "abc", "expires_in": 1800}
    )
    assert token == "abc"
    assert expires == 1800


def test_parse_token_defaults_expiry():
    _, expires = GoogleDriveFileProvider._parse_token(200, {"access_token": "abc"})
    assert expires == 3600


def test_parse_token_error_raises():
    with pytest.raises(FileProviderError) as exc:
        GoogleDriveFileProvider._parse_token(400, {"error_description": "bad refresh token"})
    assert "bad refresh token" in str(exc.value)


def test_parse_token_missing_access_token_raises():
    with pytest.raises(FileProviderError):
        GoogleDriveFileProvider._parse_token(200, {"expires_in": 10})


def test_escape_query_value_escapes_quotes_and_backslashes():
    assert _escape_query_value("a'b") == "a\\'b"
    assert _escape_query_value("a\\b") == "a\\\\b"


def test_child_query_shapes_folder_lookup():
    q = GoogleDriveFileProvider._child_query("PARENT", "Financials", folder=True)
    assert "'PARENT' in parents" in q
    assert "name = 'Financials'" in q
    assert "trashed = false" in q
    assert "mimeType = 'application/vnd.google-apps.folder'" in q


def test_child_query_non_folder():
    q = GoogleDriveFileProvider._child_query("P", "x.md", folder=False)
    assert "mimeType != 'application/vnd.google-apps.folder'" in q


def test_parse_file_maps_fields_and_size():
    sf = GoogleDriveFileProvider._parse_file(
        {
            "id": "1",
            "name": "x.md",
            "mimeType": "text/markdown",
            "webViewLink": "http://d",
            "size": "42",
        }
    )
    assert (sf.file_id, sf.name, sf.mime_type, sf.web_url, sf.size_bytes) == (
        "1",
        "x.md",
        "text/markdown",
        "http://d",
        42,
    )


def test_parse_file_handles_missing_size():
    sf = GoogleDriveFileProvider._parse_file({"id": "1"})
    assert sf.size_bytes is None
    assert sf.mime_type == "application/octet-stream"


def test_multipart_related_has_both_parts():
    ctype, body = GoogleDriveFileProvider._multipart_related(
        {"name": "x.md", "parents": ["P"]}, b"hello", "text/markdown"
    )
    boundary = ctype.split("boundary=")[1]
    assert f"--{boundary}".encode() in body
    assert body.rstrip().endswith(f"--{boundary}--".encode())
    assert b'"name": "x.md"' in body
    assert b"text/markdown" in body
    assert b"hello" in body


def test_provider_unconfigured_no_network():
    # Constructing the adapter must not touch the network (creds only resolved on use).
    p = GoogleDriveFileProvider(client_id="a" * 8, client_secret="b" * 8, refresh_token="c" * 8)
    assert p._root_folder_id == "root"


# ─────────────────────── Google Drive one-click connect (OAuth) ───────────────────────


def test_redirect_uri_appends_callback_and_strips_slash():
    assert (
        gdrive_oauth.redirect_uri("https://api.example.com/")
        == "https://api.example.com/integrations/google-drive/callback"
    )


def test_authorize_url_has_offline_consent_and_params():
    url = gdrive_oauth.authorize_url(
        client_id="cid", redirect_uri="https://api/x/callback", state="STATE"
    )
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=cid" in url
    assert "response_type=code" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=STATE" in url
    # redirect_uri and scope are URL-encoded
    assert "redirect_uri=https%3A%2F%2Fapi%2Fx%2Fcallback" in url
    assert "drive.file" in url


def test_exchange_form_shape():
    form = gdrive_oauth.exchange_form(
        code="CODE", client_id="cid", client_secret="sec", redirect_uri="https://r"
    )
    assert form == {
        "code": "CODE",
        "client_id": "cid",
        "client_secret": "sec",
        "redirect_uri": "https://r",
        "grant_type": "authorization_code",
    }


def test_parse_exchange_returns_refresh_token():
    assert gdrive_oauth.parse_exchange(200, {"refresh_token": "1//abc"}) == "1//abc"


def test_parse_exchange_error_raises():
    with pytest.raises(FileProviderError) as exc:
        gdrive_oauth.parse_exchange(400, {"error_description": "bad code"})
    assert "bad code" in str(exc.value)


def test_parse_exchange_missing_refresh_token_raises():
    with pytest.raises(FileProviderError):
        gdrive_oauth.parse_exchange(200, {"access_token": "at"})


def test_connect_configured_reflects_settings(monkeypatch):
    monkeypatch.setattr(settings, "google_oauth_client_id", "")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "")
    assert gdrive_oauth.connect_configured() is False
    monkeypatch.setattr(settings, "google_oauth_client_id", "cid")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "sec")
    assert gdrive_oauth.connect_configured() is True


@pytest.mark.asyncio
async def test_resolve_file_provider_uses_companys_own_drive(monkeypatch):
    from app.services import integrations as integrations_svc

    fallback_called = {"hit": False}

    async def _own(db, *, company_id):
        return {"refresh_token": "rt-company"}

    async def _fallback(company_id):
        fallback_called["hit"] = True
        return None

    monkeypatch.setattr(integrations_svc, "get_google_drive", _own)
    monkeypatch.setattr(integrations_svc, "_owner_google_drive", _fallback)
    provider = await integrations_svc.resolve_file_provider(object(), company_id=uuid.uuid4())
    assert isinstance(provider, GoogleDriveFileProvider)
    assert fallback_called["hit"] is False  # own creds short-circuit the founder fallback


@pytest.mark.asyncio
async def test_resolve_file_provider_falls_back_to_founder_drive(monkeypatch):
    # This company connected nothing itself, but the founder linked Drive on a
    # sibling company → the file store still resolves (connect-once-covers-all).
    from app.services import integrations as integrations_svc

    async def _none(db, *, company_id):
        return None

    async def _owner(company_id):
        return {"refresh_token": "rt-owner"}

    monkeypatch.setattr(integrations_svc, "get_google_drive", _none)
    monkeypatch.setattr(integrations_svc, "_owner_google_drive", _owner)
    provider = await integrations_svc.resolve_file_provider(object(), company_id=uuid.uuid4())
    assert isinstance(provider, GoogleDriveFileProvider)


@pytest.mark.asyncio
async def test_resolve_file_provider_none_when_founder_has_no_drive(monkeypatch):
    from app.services import integrations as integrations_svc

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(integrations_svc, "get_google_drive", _none)
    monkeypatch.setattr(integrations_svc, "_owner_google_drive", _none)
    assert await integrations_svc.resolve_file_provider(object(), company_id=uuid.uuid4()) is None


def test_oauth_state_round_trip():
    cid = uuid.uuid4()
    assert decode_oauth_state(create_oauth_state(cid)) == cid


def test_oauth_state_rejects_garbage():
    assert decode_oauth_state("not-a-jwt") is None


def test_oauth_state_rejects_access_token():
    # An access token (different audience) must not pass as OAuth state.
    from app.security import create_access_token

    assert decode_oauth_state(create_access_token(uuid.uuid4())) is None


# ─────────────────────────── files service taxonomy ───────────────────────────


class _Company:
    def __init__(self, name: str):
        self.id = uuid.uuid4()
        self.name = name


def test_provider_root_folder_defaults_to_root():
    # "root" is Drive's alias for My Drive root and a valid parent for create/list,
    # so an unset/empty stored root_folder_id must normalize to it (never "").
    common = dict(client_id="c", client_secret="s", refresh_token="r")
    assert GoogleDriveFileProvider(**common)._root_folder_id == "root"
    assert GoogleDriveFileProvider(**common, root_folder_id="")._root_folder_id == "root"
    assert GoogleDriveFileProvider(**common, root_folder_id="root")._root_folder_id == "root"
    assert GoogleDriveFileProvider(**common, root_folder_id="abc123")._root_folder_id == "abc123"


@pytest.mark.asyncio
async def test_get_root_does_a_real_call_and_resolves_id(monkeypatch):
    provider = GoogleDriveFileProvider(client_id="c", client_secret="s", refresh_token="r")
    captured: dict = {}

    class _Resp:
        content = b"{}"

        def json(self):
            return {"id": "real-root-id"}

    async def _fake_send(client, method, url, *, action, **kwargs):
        captured.update(method=method, url=url, action=action, params=kwargs.get("params"))
        return _Resp()

    monkeypatch.setattr(provider, "_send", _fake_send)
    assert await provider.get_root() == "real-root-id"
    # A real GET against the configured root (default "root") — this is what forces
    # the token refresh that actually validates the credential.
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/files/root")
    assert captured["params"] == {"fields": "id"}


@pytest.mark.asyncio
async def test_get_root_falls_back_to_configured_id_when_absent(monkeypatch):
    provider = GoogleDriveFileProvider(client_id="c", client_secret="s", refresh_token="r")

    class _Resp:
        content = b"{}"

        def json(self):
            return {}  # Drive omitted the id

    async def _fake_send(client, method, url, *, action, **kwargs):
        return _Resp()

    monkeypatch.setattr(provider, "_send", _fake_send)
    assert await provider.get_root() == "root"


@pytest.mark.asyncio
async def test_verify_google_drive_does_a_real_reachability_check(monkeypatch):
    # The verify-before-store must actually hit Drive (so a bad/expired token is
    # rejected up front) — i.e. it calls get_root, not the no-op ensure_folder([]).
    from app.services import integrations as integrations_svc

    called = {"hit": False}

    async def _fake_get_root(self):
        called["hit"] = True
        return "root"

    monkeypatch.setattr(GoogleDriveFileProvider, "get_root", _fake_get_root)
    await integrations_svc.verify_google_drive(client_id="c", client_secret="s", refresh_token="r")
    assert called["hit"] is True


@pytest.mark.asyncio
async def test_verify_google_drive_propagates_failure(monkeypatch):
    from app.services import integrations as integrations_svc

    async def _boom(self):
        raise FileProviderError("invalid_grant")

    monkeypatch.setattr(GoogleDriveFileProvider, "get_root", _boom)
    with pytest.raises(FileProviderError):
        await integrations_svc.verify_google_drive(
            client_id="c", client_secret="s", refresh_token="bad"
        )


def test_company_folder_name_sanitizes_and_appends_id():
    c = _Company("Acme / Co\nInc")
    name = files_svc.company_folder_name(c)
    assert name == f"Acme Co Inc ({str(c.id)[:8]})"


def test_company_folder_name_falls_back_to_id():
    c = _Company("")
    assert files_svc.company_folder_name(c) == f"company-{str(c.id)[:8]}"


def test_company_folder_name_is_unique_for_same_named_companies():
    # Two businesses share a name (e.g. onboarding's default "Untitled Company") —
    # they must still get distinct folders in the founder's shared Drive.
    a, b = _Company("Untitled Company"), _Company("Untitled Company")
    assert files_svc.company_folder_name(a) != files_svc.company_folder_name(b)


def test_category_path_uses_root_and_category_folder():
    c = _Company("Acme")
    path = files_svc.category_path(c, FileCategory.financial)
    assert path[0] == ".abos"
    assert path[1] == f"Acme ({str(c.id)[:8]})"
    assert path[2] == "Financials"


def test_every_category_has_a_folder():
    for cat in FileCategory:
        assert cat in files_svc.CATEGORY_FOLDERS


def test_guess_mime_by_extension():
    assert files_svc.guess_mime("a.csv") == "text/csv"
    assert files_svc.guess_mime("a.html") == "text/html"
    assert files_svc.guess_mime("noext") == "text/markdown"


def test_ensure_extension_adds_when_missing():
    assert files_svc.ensure_extension("report", "text/markdown") == "report.md"
    assert files_svc.ensure_extension("report.md", "text/markdown") == "report.md"
    assert files_svc.ensure_extension("data", "text/csv") == "data.csv"


# ─────────────────────────── tool registration ───────────────────────────

FILE_TOOL_NAMES = ("save_file", "list_company_files", "read_company_file")


def test_file_tools_registered():
    names = {s.name for s in TOOL_SPECS}
    for expected in FILE_TOOL_NAMES:
        assert expected in names


def test_handlers_match_specs():
    assert set(HANDLERS) == {s.name for s in SPECS}


def test_specs_have_object_schema():
    for spec in SPECS:
        assert spec.input_schema["type"] == "object"


def test_save_file_category_enum_excludes_communications():
    save = next(s for s in SPECS if s.name == "save_file")
    enum = save.input_schema["properties"]["category"]["enum"]
    assert "communications" not in enum  # reserved for the auto comms log
    assert "financial" in enum and "data_room" in enum and "brand" in enum


# ─────────────────────────── archive via fake provider ───────────────────────────


class FakeFileProvider:
    """In-memory FileProvider for tests (satisfies the Protocol structurally)."""

    def __init__(self):
        self.folders: dict[str, str] = {}  # path -> id
        self.files: dict[tuple[str, str], bytes] = {}  # (folder_id, name) -> content
        self._n = 0

    async def ensure_folder(self, path: list[str]) -> FolderRef:
        key = "/".join(p.strip() for p in path if p.strip())
        if key not in self.folders:
            self._n += 1
            self.folders[key] = f"folder-{self._n}"
        return FolderRef(folder_id=self.folders[key], path=key)

    async def upload_file(self, *, folder_id, name, content, mime_type) -> StoredFile:
        self.files[(folder_id, name)] = content
        return StoredFile(
            file_id=f"file-{folder_id}-{name}",
            name=name,
            mime_type=mime_type,
            web_url=f"https://drive/{name}",
            size_bytes=len(content),
        )

    async def list_folder(self, folder_id):
        return [
            StoredFile(file_id="x", name=n, mime_type="text/markdown")
            for (fid, n) in self.files
            if fid == folder_id
        ]

    async def download_file(self, file_id):
        for (fid, name), content in self.files.items():
            if file_id == f"file-{fid}-{name}":
                return content
        raise FileProviderError("not found")


class _FakeDB:
    """Minimal async session stand-in: records adds, no-op flush, returns company."""

    def __init__(self, company=None):
        self.company = company
        self.added: list = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def get(self, model, ident):
        return self.company


def test_fake_provider_is_a_file_provider():
    assert isinstance(FakeFileProvider(), FileProvider)


@pytest.mark.asyncio
async def test_archive_files_into_category_folder_and_indexes():
    provider = FakeFileProvider()
    company = _Company("Acme")
    db = _FakeDB(company)
    row = await files_svc.archive(
        db,
        provider,
        company=company,
        category=FileCategory.data_room,
        name="cap table",
        content=b"x",
        description="DD doc",
    )
    folder = f".abos/{files_svc.company_folder_name(company)}/Data Room"
    assert row.folder_path == folder
    assert row.name == "cap table.md"  # extension added
    assert row.external_id == "file-folder-1-cap table.md"
    assert row.web_url == "https://drive/cap table.md"
    assert row.category == FileCategory.data_room
    assert row.description == "DD doc"
    assert db.added == [row]
    # The file actually reached the (fake) provider.
    assert (provider.folders[folder], "cap table.md") in provider.files


@pytest.mark.asyncio
async def test_safe_archive_noops_without_provider(monkeypatch):
    async def _no_provider(db, *, company_id):
        return None

    monkeypatch.setattr(files_svc, "resolve_file_provider", _no_provider)
    out = await files_svc.safe_archive(
        _FakeDB(), company_id=uuid.uuid4(), category=FileCategory.financial, name="t", content="x"
    )
    assert out is None


@pytest.mark.asyncio
async def test_safe_archive_swallows_provider_errors(monkeypatch):
    async def _boom(db, *, company_id):
        raise FileProviderError("drive down")

    monkeypatch.setattr(files_svc, "resolve_file_provider", _boom)
    out = await files_svc.safe_archive(
        _FakeDB(), company_id=uuid.uuid4(), category=FileCategory.financial, name="t", content="x"
    )
    assert out is None  # best-effort: never raises into the caller


@pytest.mark.asyncio
async def test_safe_archive_files_when_provider_present(monkeypatch):
    provider = FakeFileProvider()
    company = _Company("Acme")

    async def _resolve(db, *, company_id):
        return provider

    monkeypatch.setattr(files_svc, "resolve_file_provider", _resolve)
    out = await files_svc.safe_archive(
        _FakeDB(company),
        company_id=company.id,
        category=FileCategory.communications,
        name="email-a@b.com-Hello",
        content="To: a@b.com\nSubject: Hello\n\nhi",
    )
    assert out is not None
    assert out.folder_path == f".abos/{files_svc.company_folder_name(company)}/Communications"
