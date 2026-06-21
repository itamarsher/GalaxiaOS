"""External communications: the outbound-message index and its approval setting.

The index (``GET .../external-messages``) is the founder's audit trail of every
message the fleet has tried to send outside the company. The setting
(``GET``/``PUT .../settings/external-comms-approval``) flips a single governance
policy that forces every such message through the founder's decision inbox — the
"approve everything during early cycles" guardrail. When on, gated messages show
up as pending decisions that can be discussed with full context before sign-off.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.deps import CompanyDep, DbDep
from app.models import Agent
from app.models.enums import ExternalMessageStatus
from app.schemas import (
    ExternalApprovalSetting,
    ExternalApprovalUpdate,
    ExternalMessageOut,
)
from app.services import external_messages as ext
from app.services import governance as gov

router = APIRouter(prefix="/companies/{company_id}", tags=["communications"])


@router.get("/external-messages", response_model=list[ExternalMessageOut])
async def list_external_messages(
    company: CompanyDep,
    db: DbDep,
    status: str | None = Query(default=None),
    limit: int = Query(default=200, le=500),
):
    status_enum = ExternalMessageStatus(status) if status else None
    messages = await ext.list_messages(
        db, company_id=company.id, status=status_enum, limit=limit
    )
    # Join the agent's human-readable name/role so the log isn't opaque ids.
    agent_ids = {m.agent_id for m in messages if m.agent_id}
    agents: dict = {}
    if agent_ids:
        agents = {
            a.id: a
            for a in (await db.scalars(select(Agent).where(Agent.id.in_(agent_ids)))).all()
        }
    out = []
    for m in messages:
        item = ExternalMessageOut.model_validate(m)
        agent = agents.get(m.agent_id)
        item.agent_name = agent.name if agent else None
        item.agent_role = agent.role.value if agent else None
        out.append(item)
    return out


@router.get(
    "/settings/external-comms-approval", response_model=ExternalApprovalSetting
)
async def get_external_comms_approval(company: CompanyDep, db: DbDep):
    enabled = await gov.get_external_comms_approval(db, company_id=company.id)
    return ExternalApprovalSetting(enabled=enabled)


@router.put(
    "/settings/external-comms-approval", response_model=ExternalApprovalSetting
)
async def set_external_comms_approval(
    company: CompanyDep, body: ExternalApprovalUpdate, db: DbDep
):
    enabled = await gov.set_external_comms_approval(
        db, company_id=company.id, enabled=body.enabled
    )
    await db.commit()
    return ExternalApprovalSetting(enabled=enabled)
