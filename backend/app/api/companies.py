"""Company views: detail, org chart, agents (pause/resume), runs/tasks, memory."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CompanyDep, DbDep
from app.models import Agent, AgentEdge, MemoryEntry, Task
from app.models.enums import AgentStatus, TaskStatus
from app.schemas import (
    AgentEdgeOut,
    AgentOut,
    CompanyOut,
    MemoryOut,
    OrgChartOut,
    TaskOut,
)

router = APIRouter(prefix="/companies/{company_id}", tags=["companies"])


@router.get("", response_model=CompanyOut)
async def get_company(company: CompanyDep):
    return company


@router.get("/org", response_model=OrgChartOut)
async def org_chart(company: CompanyDep, db: DbDep):
    agents = (await db.scalars(select(Agent).where(Agent.company_id == company.id))).all()
    edges = (await db.scalars(select(AgentEdge).where(AgentEdge.company_id == company.id))).all()
    return OrgChartOut(
        agents=[AgentOut.model_validate(a) for a in agents],
        edges=[AgentEdgeOut.model_validate(e) for e in edges],
    )


@router.get("/agents", response_model=list[AgentOut])
async def list_agents(company: CompanyDep, db: DbDep):
    return (await db.scalars(select(Agent).where(Agent.company_id == company.id))).all()


@router.post("/agents/{agent_id}/pause", response_model=AgentOut)
async def pause_agent(company: CompanyDep, agent_id: uuid.UUID, db: DbDep):
    return await _set_agent_status(db, company.id, agent_id, AgentStatus.paused)


@router.post("/agents/{agent_id}/resume", response_model=AgentOut)
async def resume_agent(company: CompanyDep, agent_id: uuid.UUID, db: DbDep):
    return await _set_agent_status(db, company.id, agent_id, AgentStatus.active)


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(company: CompanyDep, db: DbDep, status: TaskStatus | None = None):
    stmt = select(Task).where(Task.company_id == company.id).order_by(Task.created_at.desc())
    if status is not None:
        stmt = stmt.where(Task.status == status)
    return (await db.scalars(stmt.limit(200))).all()


@router.get("/memory", response_model=list[MemoryOut])
async def list_memory(company: CompanyDep, db: DbDep, q: str | None = None):
    stmt = (
        select(MemoryEntry)
        .where(MemoryEntry.company_id == company.id)
        .order_by(MemoryEntry.created_at.desc())
    )
    if q:
        stmt = stmt.where(MemoryEntry.content.ilike(f"%{q}%"))
    return (await db.scalars(stmt.limit(100))).all()


async def _set_agent_status(db, company_id, agent_id, new_status):
    agent = await db.scalar(
        select(Agent).where(Agent.company_id == company_id, Agent.id == agent_id)
    )
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    agent.status = new_status
    await db.commit()
    return agent
