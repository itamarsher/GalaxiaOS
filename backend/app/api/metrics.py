"""Metrics endpoints: record and recall real-world outcome signals."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import CompanyDep, DbDep
from app.models.enums import MetricSource
from app.schemas.metrics import MetricSignalIn, MetricSignalOut
from app.services import metrics

router = APIRouter(prefix="/companies/{company_id}", tags=["metrics"])


@router.post("/metrics", response_model=MetricSignalOut)
async def record_metric(company: CompanyDep, body: MetricSignalIn, db: DbDep):
    signal = await metrics.record_signal(
        db,
        company_id=company.id,
        name=body.name,
        value=body.value,
        unit=body.unit,
        source=MetricSource.founder,
        note=body.note,
    )
    await db.commit()
    return signal


@router.get("/metrics", response_model=list[MetricSignalOut])
async def list_metrics(
    company: CompanyDep, db: DbDep, limit: int = Query(default=8, ge=1, le=100)
):
    return await metrics.latest_signals(db, company_id=company.id, limit=limit)
