"""The bundle-backed repo store — a git repo as a file, no server (RFC 0003).

A coding function keeps durable code state without a git server or GitHub: the repo
is a ``git bundle`` (a single file that is itself a valid git remote — full history
and all refs) stored via the existing :class:`FileProvider` seam under the ``code``
category. Galaxia treats the bundle as **opaque bytes**; all git runs in the
worker's sandbox (clone from the bundle, edit, re-bundle, push back).

This module is that store: save/load the canonical bundle per named repo, list a
company's repos, and the base64 transport helpers the MCP surface uses (a bundle is
binary; MCP JSON is text). Bundles reuse the ``CompanyFile`` manifest, so there is
no new table — a repo's canonical bundle is the file named ``<repo>.bundle`` in the
company's ``code`` folder, overwritten in place on each push (history lives inside
the bundle, not in versioned filenames).
"""

from __future__ import annotations

import base64
import json
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.integrations.files import FileProvider
from app.models import Company, CompanyFile
from app.models.enums import FileCategory
from app.services import data_policy
from app.services import files as files_svc

_BUNDLE_MIME = "application/x-git-bundle"
_SUFFIX = ".bundle"
#: A repo name must be a safe, single path segment (no slashes/dots/spaces games).
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class RepoError(ValueError):
    """A bad repo request (invalid name, oversized bundle, corrupt payload)."""


def normalize_name(repo: str) -> str:
    """Validate + return a repo name, or raise :class:`RepoError`."""
    name = (repo or "").strip()
    if name.endswith(_SUFFIX):
        name = name[: -len(_SUFFIX)]
    if not _NAME_RE.match(name):
        raise RepoError(
            "invalid repo name — use letters, digits, '.', '_' or '-' (max 64 chars)"
        )
    return name


def _filename(repo: str) -> str:
    return f"{repo}{_SUFFIX}"


def encode_bundle(content: bytes) -> str:
    """Bundle bytes → base64 text for MCP transport."""
    return base64.b64encode(content).decode("ascii")


def decode_bundle(payload: str) -> bytes:
    """Base64 text → bundle bytes; raises :class:`RepoError` on a corrupt payload."""
    try:
        return base64.b64decode((payload or "").encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise RepoError("bundle payload is not valid base64") from exc


def _check_size(content: bytes) -> None:
    cap = settings.repo_max_bundle_bytes
    if cap and len(content) > cap:
        raise RepoError(
            f"bundle is too large ({len(content) // 1024} KB; limit {cap // 1024} KB)"
        )


async def save_bundle(
    db: AsyncSession,
    provider: FileProvider,
    *,
    company: Company,
    repo: str,
    content: bytes,
    head: str | None = None,
    note: str | None = None,
) -> CompanyFile:
    """Store ``content`` as the canonical bundle for ``repo`` (overwrites in place).

    ``head`` (the pushed branch/ref) and ``note`` are stamped into the manifest
    description so the store shows what state it holds without opening the bundle.
    Raises :class:`RepoError` for a bad name or an oversized bundle; the caller
    commits.
    """
    repo = normalize_name(repo)
    _check_size(content)
    # Write the bundle directly (not via files.archive) so the binary blob keeps its
    # exact ``<repo>.bundle`` name and git-bundle MIME — archive's doc-oriented naming
    # would rewrite it to a text extension.
    folder = await provider.ensure_folder(
        files_svc.category_path(company, FileCategory.code)
    )
    filename = _filename(repo)
    stored = await provider.upload_file(
        folder_id=folder.folder_id, name=filename, content=content, mime_type=_BUNDLE_MIME
    )
    size = stored.size_bytes if stored.size_bytes is not None else len(content)
    description = json.dumps({"head": head, "note": note})
    # Upsert the manifest row: the provider replaces the file in place, so one repo
    # keeps one CompanyFile row (the canonical bundle) rather than a row per push.
    row = await db.scalar(
        select(CompanyFile).where(
            CompanyFile.company_id == company.id,
            CompanyFile.category == FileCategory.code,
            CompanyFile.name == filename,
        )
    )
    if row is None:
        row = CompanyFile(
            company_id=company.id,
            category=FileCategory.code,
            labels=data_policy.default_labels_for_category(FileCategory.code.value),
            name=filename,
            provider="google_drive",
        )
        db.add(row)
    row.description = description
    row.mime_type = stored.mime_type or _BUNDLE_MIME
    row.folder_path = folder.path
    row.external_id = stored.file_id
    row.web_url = stored.web_url
    row.size_bytes = size
    await db.flush()
    return row


async def load_bundle(
    db: AsyncSession,
    provider: FileProvider,
    *,
    company_id: uuid.UUID,
    repo: str,
) -> bytes | None:
    """The canonical bundle bytes for ``repo``, or ``None`` if it doesn't exist yet."""
    repo = normalize_name(repo)
    row = await files_svc.find_file(db, company_id=company_id, name=_filename(repo))
    if row is None or not row.external_id or row.category != FileCategory.code:
        return None
    return await provider.download_file(row.external_id)


def _meta(row: CompanyFile) -> dict:
    try:
        return json.loads(row.description) if row.description else {}
    except (ValueError, TypeError):
        return {}


async def list_repos(db: AsyncSession, *, company_id: uuid.UUID) -> list[dict]:
    """Every repo the company holds (name, head, size, web_url), newest first."""
    rows = await files_svc.list_files(
        db, company_id=company_id, category=FileCategory.code
    )
    out: list[dict] = []
    for row in rows:
        if not row.name.endswith(_SUFFIX):
            continue
        meta = _meta(row)
        out.append({
            "repo": row.name[: -len(_SUFFIX)],
            "head": meta.get("head"),
            "note": meta.get("note"),
            "size_bytes": row.size_bytes,
            "web_url": row.web_url,
        })
    return out
