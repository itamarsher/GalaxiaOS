"""Company file store — read-only listing of filed documents.

Surfaces the :class:`~app.models.file.CompanyFile` manifest so the founder (and the
UI) can see what's in the external store — the data room, the financial trail, the
brand library — and open each item via its provider link, without leaving ABOS.
The files themselves live in the company's Drive; this is the index over them.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import CompanyDep, DbDep
from app.models.enums import FileCategory
from app.schemas import CompanyFileOut
from app.services import files as files_svc

router = APIRouter(prefix="/companies/{company_id}/files", tags=["files"])


@router.get("", response_model=list[CompanyFileOut])
async def list_company_files(
    company: CompanyDep,
    db: DbDep,
    category: FileCategory | None = Query(default=None),
):
    return await files_svc.list_files(db, company_id=company.id, category=category)
