"""Founder-facing reports (artifacts): list, read, and generate on demand."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.deps import CompanyDep, DbDep
from app.schemas import ArtifactGenerateRequest, ArtifactListOut, ArtifactOut
from app.services import artifacts as artifacts_svc

router = APIRouter(prefix="/companies/{company_id}/reports", tags=["reports"])


@router.get("", response_model=list[ArtifactListOut])
async def list_reports(company: CompanyDep, db: DbDep):
    return await artifacts_svc.list_artifacts(db, company_id=company.id)


@router.get("/{artifact_id}", response_model=ArtifactOut)
async def get_report(company: CompanyDep, artifact_id: uuid.UUID, db: DbDep):
    artifact = await artifacts_svc.get_artifact(db, company_id=company.id, artifact_id=artifact_id)
    if artifact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    return artifact


@router.post("/generate", response_model=ArtifactOut, status_code=status.HTTP_201_CREATED)
async def generate_report(company: CompanyDep, body: ArtifactGenerateRequest, db: DbDep):
    artifact = await artifacts_svc.generate_artifact(
        db, company_id=company.id, kind=body.kind, instructions=body.instructions
    )
    if artifact is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Add a provider API key in Settings to generate reports.",
        )
    await db.commit()
    return artifact
