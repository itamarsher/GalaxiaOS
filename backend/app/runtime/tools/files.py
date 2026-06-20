"""File tools: give agents a durable, organized external file store.

These are how an agent puts a deliverable, a financial record, a due-diligence
document, a brand guideline, or any knowledge worth keeping into the company's
file provider (Google Drive today) under ``.abos/<company>/<Category>/`` — and how
it lists and reads them back later. Filing is a genuine external write; without a
connected provider the tools report the capability is unsupported (via
``unsupported_capability``) rather than pretending a doc was saved, so nothing
phantom ever enters the audit trail.

The store is provider-agnostic (see :mod:`app.integrations.files`); the taxonomy
and indexing live in :mod:`app.services.files`.
"""

from __future__ import annotations

from app.integrations.files import FileProviderError
from app.models import Agent, Company, Task
from app.models.enums import FileCategory, MemoryType
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome, unsupported_capability
from app.services import files as files_svc
from app.services import memory as memory_svc
from app.services.integrations import resolve_file_provider

#: Category enum values exposed to the model, with what each folder is for.
_CATEGORY_HELP = (
    "artifact = a deliverable you produced (copy, spec, doc, plan); "
    "financial = invoices/statements/transactions kept for the audit trail; "
    "data_room = due-diligence-ready documents for investors/buyers; "
    "brand = shared messaging or design guidelines; "
    "inbox = a noteworthy file received via an external channel; "
    "knowledge = anything else worth retaining in external storage."
)
_CATEGORIES = [c.value for c in FileCategory if c != FileCategory.communications]


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="save_file",
        description=(
            "File a document into the company's external file store (organized "
            "folders in the founder's Drive) so it is retained, shareable, and "
            "audit/DD-ready. Use this for anything worth keeping outside chat: "
            "deliverables, financial records, data-room docs, brand/messaging "
            "guidelines, or received files. Choose the category by purpose — "
            f"{_CATEGORY_HELP} Re-saving the same filename updates it in place."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": _CATEGORIES},
                "name": {
                    "type": "string",
                    "description": "Filename, e.g. 'Q3 revenue.md' or 'pitch-deck-outline.md'.",
                },
                "content": {"type": "string", "description": "The full file content (text)."},
                "description": {
                    "type": "string",
                    "description": "Optional one-line note on what this file is (for the index).",
                },
            },
            "required": ["category", "name", "content"],
        },
    ),
    ToolSpec(
        name="list_company_files",
        description=(
            "List the documents already filed in the company's external store, "
            "optionally limited to one category, so you can see what exists before "
            "creating or referencing a document."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": _CATEGORIES},
            },
        },
    ),
    ToolSpec(
        name="read_company_file",
        description=(
            "Read back the content of a previously filed document by name "
            "(extension optional), e.g. to reuse the brand guidelines or a prior "
            "deliverable."
        ),
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    ),
]

_UNSUPPORTED_HINT = (
    "No file store is connected. Ask the founder to connect Google Drive in "
    "Settings (or call `request_capability`)."
)


def _parse_category(raw: object) -> FileCategory | None:
    try:
        return FileCategory(str(raw).strip().lower())
    except ValueError:
        return None


async def _save_file(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    category = _parse_category(args.get("category"))
    if category is None or category == FileCategory.communications:
        return ToolOutcome(
            observation=f"Unknown category; choose one of {', '.join(_CATEGORIES)}.",
            is_error=True,
        )
    name = str(args.get("name") or "").strip()
    content = str(args.get("content") or "")
    if not name:
        return ToolOutcome(observation="A filename is required.", is_error=True)
    if not content.strip():
        return ToolOutcome(observation="File content is empty; nothing to save.", is_error=True)

    provider = await resolve_file_provider(db, company_id=task.company_id)
    if provider is None:
        return unsupported_capability("Saving a file", hint=_UNSUPPORTED_HINT)

    company = await db.get(Company, task.company_id)
    if company is None:
        return ToolOutcome(observation="company not found; cannot file.", is_error=True)
    try:
        row = await files_svc.archive(
            db,
            provider,
            company=company,
            category=category,
            name=name,
            content=content.encode("utf-8"),
            source_task_id=task.id,
            description=str(args.get("description") or "").strip() or None,
        )
    except FileProviderError as exc:
        return ToolOutcome(observation=f"saving the file failed: {exc}", is_error=True)

    # Breadcrumb in Company Memory so the filing is recallable in planning context.
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title=f"Filed {category.value}: {row.name}"[:500],
        content=f"Saved to {row.folder_path}/{row.name}."
        + (f"\n{row.description}" if row.description else ""),
        source_task_id=task.id,
    )
    where = f"{row.folder_path}/{row.name}"
    link = f" ({row.web_url})" if row.web_url else ""
    return ToolOutcome(observation=f"filed {category.value} document at {where}{link}")


async def _list_company_files(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    category = _parse_category(args.get("category")) if args.get("category") else None
    rows = await files_svc.list_files(db, company_id=task.company_id, category=category)
    if not rows:
        scope = f" in {category.value}" if category else ""
        return ToolOutcome(observation=f"No files filed yet{scope}.")
    lines = [
        f"- [{r.category.value}] {r.name}"
        + (f" — {r.description}" if r.description else "")
        + (f" ({r.web_url})" if r.web_url else "")
        for r in rows
    ]
    return ToolOutcome(observation="Filed documents:\n" + "\n".join(lines[:50]))


async def _read_company_file(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    name = str(args.get("name") or "").strip()
    if not name:
        return ToolOutcome(observation="A file name is required.", is_error=True)
    row = await files_svc.find_file(db, company_id=task.company_id, name=name)
    if row is None:
        return ToolOutcome(observation=f"No filed document named {name!r}.", is_error=True)

    provider = await resolve_file_provider(db, company_id=task.company_id)
    if provider is None or not row.external_id:
        return unsupported_capability("Reading a file", hint=_UNSUPPORTED_HINT)
    try:
        data = await provider.download_file(row.external_id)
    except FileProviderError as exc:
        return ToolOutcome(observation=f"reading the file failed: {exc}", is_error=True)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ToolOutcome(
            observation=f"{row.name} is a binary file ({row.mime_type}); not shown as text."
        )
    return ToolOutcome(observation=f"{row.name}:\n{text[:4000]}")


HANDLERS = {
    "save_file": _save_file,
    "list_company_files": _list_company_files,
    "read_company_file": _read_company_file,
}
