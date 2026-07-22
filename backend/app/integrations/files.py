"""File-provider seam — the company's external file store.

A :class:`FileProvider` is the third decoupling seam alongside ``LLMProvider``
(which vendor answers) and ``AgentBackend`` (how an agent runs): it abstracts
*where the company's files live*. Today the only adapter is Google Drive
(:class:`~app.integrations.gdrive.GoogleDriveFileProvider`), writing into the
founder's personal Drive under ``.galaxia/<company>/…``; tomorrow it could be S3,
Dropbox, or a SharePoint site without touching the runtime, the service layer, or
the agent tools.

The contract is deliberately small and folder-oriented so the service layer
(:mod:`app.services.files`) can own the taxonomy:

- :meth:`FileProvider.ensure_folder` — idempotently resolve (creating as needed) a
  nested folder *path* from the store root, returning its id.
- :meth:`FileProvider.upload_file` — write bytes into a folder, replacing a
  same-named file so re-archiving a doc updates it in place (single source of
  truth) rather than piling up duplicates.
- :meth:`FileProvider.list_folder` / :meth:`FileProvider.download_file` — read back
  what's there.

Like the other seams there is **no simulated provider**: a company without
credentials resolves to ``None`` and the file tools report the capability is
unsupported, so an agent never believes a doc was filed when it wasn't.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class FolderRef:
    """A resolved folder in the store: its provider id and human-readable path."""

    folder_id: str
    path: str  # e.g. ".galaxia/Acme/Financials"


@dataclass(frozen=True)
class StoredFile:
    """A file that exists in the store."""

    file_id: str
    name: str
    mime_type: str
    web_url: str | None = None  # a link a human can open (Drive webViewLink)
    size_bytes: int | None = None


class FileProviderError(RuntimeError):
    """Raised when a file operation fails (missing creds, vendor/API error)."""


class FileProviderAuthError(FileProviderError):
    """Raised when the *stored credential itself* is dead (expired/revoked),
    as opposed to a transient network or API failure. Google, for instance,
    returns this for a refresh token it will keep rejecting forever — so a
    caller catching this specifically can clear the dead credential instead of
    surfacing the same opaque error on every subsequent call."""


@runtime_checkable
class FileProvider(Protocol):
    async def ensure_folder(self, path: list[str]) -> FolderRef:
        """Resolve the folder at ``path`` (a list of nested folder names from the
        store root), creating any missing segments. Idempotent. Raises
        :class:`FileProviderError` on failure."""
        ...

    async def upload_file(
        self, *, folder_id: str, name: str, content: bytes, mime_type: str
    ) -> StoredFile:
        """Write ``content`` as ``name`` into ``folder_id``. If a file with that
        name already exists in the folder it is updated in place (so re-filing a
        document replaces it rather than creating a duplicate). Raises
        :class:`FileProviderError` on failure."""
        ...

    async def list_folder(self, folder_id: str) -> list[StoredFile]:
        """List the (non-folder) files directly under ``folder_id``."""
        ...

    async def download_file(self, file_id: str) -> bytes:
        """Return the raw bytes of ``file_id``. Raises :class:`FileProviderError`."""
        ...
