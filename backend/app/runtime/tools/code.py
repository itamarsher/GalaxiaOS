"""Codebase-reading tools: let agents read THIS repository.

Two read-only, zero-cost tools that expose the source tree to any agent so it can
understand how the company's own systems are wired before acting (the Data agent
relies on this to reason about internal data flows, but every agent has access).

Both tools are sandboxed to the repository root: a path is resolved to its real
location and rejected if it escapes the repo (path traversal) or doesn't exist —
the tools can never read outside the checked-out source tree. They perform no
network or DB I/O and route no charge through the cost meter, so they are free.
"""

from __future__ import annotations

from pathlib import Path

from app.models import Agent, Task
from app.providers.base import ToolSpec
from app.runtime.tools.base import DEFAULT_MAX_OBSERVATION_CHARS, ToolOutcome

# Repo root is the parent of ``backend/``. This file lives at
# ``<root>/backend/app/runtime/tools/code.py``, so walk up five levels.
_REPO_ROOT = Path(__file__).resolve().parents[4]

# Directories that are never source: VCS metadata, caches, dependencies, and
# build output. Any path component matching one of these is skipped.
_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "dist",
        "build",
        ".turbo",
        ".idea",
        ".vscode",
        "coverage",
        "htmlcov",
        ".egg-info",
    }
)

# Binary / non-source file extensions to omit from listings and refuse to read.
_BINARY_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
        ".so",
        ".o",
        ".a",
        ".dylib",
        ".dll",
        ".exe",
        ".bin",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".svg",
        ".webp",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".whl",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".lock",
    }
)

_MAX_FILES = 400
_MAX_READ_CHARS = DEFAULT_MAX_OBSERVATION_CHARS

SPECS: list[ToolSpec] = [
    ToolSpec(
        name="list_repo_files",
        description=(
            "List source files in this company's own codebase (relative paths), so "
            "you can understand how its systems are wired. Read-only and free. "
            "Optionally restrict to a subdirectory. Junk (.git, node_modules, build "
            "artifacts, binaries) is excluded and the listing is capped."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "subdir": {
                    "type": "string",
                    "description": "Optional repo-relative subdirectory to list under.",
                }
            },
        },
    ),
    ToolSpec(
        name="read_repo_file",
        description=(
            "Read the text of a file in this company's own codebase by its "
            "repo-relative path. Read-only and free; text files only, output capped."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repo-relative path of the file to read.",
                }
            },
            "required": ["path"],
        },
    ),
]


def _resolve_within_repo(raw: str) -> Path | None:
    """Resolve ``raw`` under the repo root, or ``None`` if it escapes the root.

    Joining first and resolving second collapses any ``..`` segments, and the
    ``is_relative_to`` check then rejects anything that climbed out of the tree —
    so absolute paths and ``../`` traversal both fail closed.
    """
    candidate = (_REPO_ROOT / raw).resolve()
    if candidate != _REPO_ROOT and not candidate.is_relative_to(_REPO_ROOT):
        return None
    return candidate


def _is_excluded(rel: Path) -> bool:
    """True if any path component is an excluded dir or the suffix is binary."""
    if any(part in _EXCLUDED_DIRS for part in rel.parts):
        return True
    return rel.suffix.lower() in _BINARY_SUFFIXES


async def _list_repo_files(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    subdir = str(args.get("subdir") or "").strip()
    root = _resolve_within_repo(subdir) if subdir else _REPO_ROOT
    if root is None:
        return ToolOutcome(
            observation=f"path {subdir!r} is outside the repository", is_error=True
        )
    if not root.exists() or not root.is_dir():
        return ToolOutcome(observation=f"directory {subdir!r} not found", is_error=True)

    files: list[str] = []
    truncated = False
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(_REPO_ROOT)
        if _is_excluded(rel):
            continue
        if len(files) >= _MAX_FILES:
            truncated = True
            break
        files.append(rel.as_posix())

    if not files:
        return ToolOutcome(observation=f"no source files under {subdir or '.'}")
    header = f"{len(files)} files under {subdir or '.'}"
    if truncated:
        header += f" (capped at {_MAX_FILES})"
    return ToolOutcome(observation=header + ":\n" + "\n".join(files))


async def _read_repo_file(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    raw = str(args.get("path") or "").strip()
    if not raw:
        return ToolOutcome(observation="path is required", is_error=True)
    path = _resolve_within_repo(raw)
    if path is None:
        return ToolOutcome(observation=f"path {raw!r} is outside the repository", is_error=True)
    if not path.exists() or not path.is_file():
        return ToolOutcome(observation=f"file {raw!r} not found", is_error=True)
    rel = path.relative_to(_REPO_ROOT)
    if rel.suffix.lower() in _BINARY_SUFFIXES:
        return ToolOutcome(observation=f"{raw!r} is a binary file; not readable", is_error=True)
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        return ToolOutcome(observation=f"could not read {raw!r}: {exc}", is_error=True)
    if len(text) > _MAX_READ_CHARS:
        text = text[:_MAX_READ_CHARS] + f"\n… (truncated at {_MAX_READ_CHARS} chars)"
    return ToolOutcome(observation=f"{rel.as_posix()}:\n{text}")


HANDLERS = {
    "list_repo_files": _list_repo_files,
    "read_repo_file": _read_repo_file,
}
