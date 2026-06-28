"""Files service — the company's organized external file store.

Owns the *taxonomy* on top of the provider-agnostic
:class:`~app.integrations.files.FileProvider` seam: every company gets a single
root folder (``.galaxia`` by default) in the founder's Drive, a sub-folder per
company, and a fixed set of category folders under that — chosen so the store can
satisfy the four goals the file provider exists for:

    .galaxia/<company>/
      ├── Artifacts/        every deliverable the agents produce
      ├── Financials/       invoices, statements, transactions — audit trail
      ├── Data Room/        due-diligence-ready documents
      ├── Brand & Messaging/ shared messaging + design guidelines
      ├── Inbox/            noteworthy files received via external channels
      ├── Communications/   outbound comms log (e.g. emails the agents send)
      └── Knowledge/        anything else worth retaining externally

Each upload also writes a :class:`~app.models.file.CompanyFile` row so the store
stays listable and auditable from the database even when Drive is unreachable.

Two entry points:
- :func:`archive` — file a document and record it (raises on provider failure).
- :func:`safe_archive` — best-effort wrapper for auto-archive hooks in the hot
  path (publish, send_email, record_transaction): resolves the provider, files the
  doc, and *never* raises, so a Drive hiccup can't break the action it shadows.

Everything is tenant-scoped: callers pass the ``company`` resolved from the runtime
context and queries never cross that boundary (RLS is the second line of defence).
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.integrations.files import FileProvider
from app.models import Company, CompanyFile
from app.models.enums import FileCategory
from app.services.integrations import resolve_file_provider

_log = logging.getLogger("app.files")

#: Category → human folder name (the second-level taxonomy under the company folder).
CATEGORY_FOLDERS: dict[FileCategory, str] = {
    FileCategory.artifact: "Artifacts",
    FileCategory.financial: "Financials",
    FileCategory.data_room: "Data Room",
    FileCategory.brand: "Brand & Messaging",
    FileCategory.inbox: "Inbox",
    FileCategory.communications: "Communications",
    FileCategory.knowledge: "Knowledge",
}

#: Extension → MIME for the handful of text formats agents produce.
_MIME_BY_EXT: dict[str, str] = {
    "md": "text/markdown",
    "markdown": "text/markdown",
    "txt": "text/plain",
    "csv": "text/csv",
    "json": "application/json",
    "html": "text/html",
    "htm": "text/html",
}
_DEFAULT_MIME = "text/markdown"


def company_folder_name(company: Company) -> str:
    """A Drive-safe, per-company-UNIQUE folder name (sanitized name + short id).

    The short id suffix is what guarantees each company gets its OWN subfolder:
    the founder's Drive is shared across every business they launch (see
    ``resolve_file_provider``), and distinct companies routinely share a name —
    onboarding even creates them all as "Untitled Company" — so keying the folder
    on the name alone would mix two businesses' files into one folder. The id is
    unique per company, so the folder never collides; the readable name is kept as
    a prefix so the founder can still tell the folders apart at a glance.
    """
    cleaned = re.sub(r"[\\/\r\n\t]+", " ", (company.name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()[:100].strip()
    short_id = str(company.id)[:8]
    return f"{cleaned} ({short_id})" if cleaned else f"company-{short_id}"


def category_path(company: Company, category: FileCategory) -> list[str]:
    """The folder path (from the store root) for a company's category folder."""
    return [settings.gdrive_root_folder, company_folder_name(company), CATEGORY_FOLDERS[category]]


def guess_mime(name: str) -> str:
    """MIME type for a filename by extension (defaults to Markdown)."""
    _, _, ext = name.rpartition(".")
    return _MIME_BY_EXT.get(ext.lower(), _DEFAULT_MIME) if ext and ext != name else _DEFAULT_MIME


def safe_filename(name: str) -> str:
    """A clean, single-line filename (no slashes/control chars; collapsed spaces)."""
    cleaned = re.sub(r"[\\/\r\n\t]+", " ", (name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:200] or "untitled"


def ensure_extension(name: str, mime_type: str) -> str:
    """Give a name a sensible extension when it has none, so Drive shows it usefully."""
    name = name.strip()
    base, _, ext = name.rpartition(".")
    if base and ext and len(ext) <= 5:
        return name
    suffix = {
        "text/markdown": "md",
        "text/plain": "txt",
        "text/csv": "csv",
        "application/json": "json",
        "text/html": "html",
    }.get(mime_type, "md")
    return f"{name}.{suffix}"


async def archive(
    db: AsyncSession,
    provider: FileProvider,
    *,
    company: Company,
    category: FileCategory,
    name: str,
    content: bytes,
    mime_type: str | None = None,
    source_task_id: uuid.UUID | None = None,
    description: str | None = None,
) -> CompanyFile:
    """File ``content`` into the company's ``category`` folder and index it.

    Resolves (creating as needed) ``.galaxia/<company>/<Category>/``, uploads the file
    (replacing a same-named one in place), then writes the :class:`CompanyFile`
    manifest row. Raises :class:`FileProviderError` if the provider call fails — the
    DB row is only written after a successful upload, so a failure leaves no
    phantom record.
    """
    mime = mime_type or guess_mime(name)
    filename = ensure_extension(safe_filename(name), mime)
    path = category_path(company, category)
    folder = await provider.ensure_folder(path)
    stored = await provider.upload_file(
        folder_id=folder.folder_id, name=filename, content=content, mime_type=mime
    )
    row = CompanyFile(
        company_id=company.id,
        category=category,
        name=stored.name or filename,
        description=description,
        mime_type=stored.mime_type or mime,
        folder_path=folder.path,
        provider="google_drive",
        external_id=stored.file_id,
        web_url=stored.web_url,
        size_bytes=stored.size_bytes if stored.size_bytes is not None else len(content),
        source_task_id=source_task_id,
    )
    db.add(row)
    await db.flush()
    return row


async def safe_archive(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    category: FileCategory,
    name: str,
    content: str | bytes,
    mime_type: str | None = None,
    source_task_id: uuid.UUID | None = None,
    description: str | None = None,
) -> CompanyFile | None:
    """Best-effort archive for auto-hooks: never raises, never breaks the caller.

    Returns the :class:`CompanyFile` on success, or ``None`` when no file provider
    is connected or the provider errors. Provider I/O happens before any DB write,
    so a network failure leaves the caller's transaction untouched.
    """
    try:
        provider = await resolve_file_provider(db, company_id=company_id)
        if provider is None:
            return None
        company = await db.get(Company, company_id)
        if company is None:
            return None
        body = content.encode("utf-8") if isinstance(content, str) else content
        return await archive(
            db,
            provider,
            company=company,
            category=category,
            name=name,
            content=body,
            mime_type=mime_type,
            source_task_id=source_task_id,
            description=description,
        )
    except Exception as exc:  # noqa: BLE001 — auto-archive must never break the action it shadows
        _log.warning("auto-archive to file store failed (%s): %s", category.value, exc)
        return None


async def list_files(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    category: FileCategory | None = None,
    limit: int = 200,
) -> list[CompanyFile]:
    """The company's filed documents (most recent first), optionally one category."""
    stmt = select(CompanyFile).where(CompanyFile.company_id == company_id)
    if category is not None:
        stmt = stmt.where(CompanyFile.category == category)
    stmt = stmt.order_by(CompanyFile.created_at.desc()).limit(limit)
    return list(await db.scalars(stmt))


async def find_file(db: AsyncSession, *, company_id: uuid.UUID, name: str) -> CompanyFile | None:
    """The most recent filed document whose name matches ``name`` (case-insensitive)."""
    target = name.strip().lower()
    rows = await list_files(db, company_id=company_id)
    for row in rows:
        if row.name.lower() == target:
            return row
    # Fall back to a prefix match so callers can omit the extension.
    for row in rows:
        if row.name.lower().startswith(target):
            return row
    return None
