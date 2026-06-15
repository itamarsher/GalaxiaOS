"""Pydantic v2 request/response DTOs (the source of truth for the OpenAPI schema)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class ORMModel(BaseModel):
    model_config = {"from_attributes": True}


# ── Auth ─────────────────────────────────────────────────────────────────────
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: uuid.UUID
    email: str


# ── Onboarding ───────────────────────────────────────────────────────────────
class OnboardingStartRequest(BaseModel):
    mission_text: str = Field(min_length=4)
    budget_cents: int = Field(gt=0, description="Monthly budget in cents, e.g. 50000 = $500")
    constraints: list[str] = Field(default_factory=list)


class CompanyOut(ORMModel):
    id: uuid.UUID
    name: str
    status: str
    mission_id: uuid.UUID | None = None


class KeyResultOut(ORMModel):
    id: uuid.UUID
    metric: str
    target_value: float | None
    current_value: float
    unit: str | None


class ObjectiveOut(ORMModel):
    id: uuid.UUID
    title: str
    rationale: str | None
    priority: int
    status: str


class AgentOut(ORMModel):
    id: uuid.UUID
    role: str
    name: str
    autonomy_level: str
    status: str
    monthly_budget_cents: int | None
    reports_to_agent_id: uuid.UUID | None
    backend_type: str
    source: str


class AgentEdgeOut(ORMModel):
    from_agent_id: uuid.UUID
    to_agent_id: uuid.UUID
    relation: str


class OrgChartOut(BaseModel):
    agents: list[AgentOut]
    edges: list[AgentEdgeOut]


class InvestmentReviewOut(ORMModel):
    id: uuid.UUID
    persona: str
    stance: str
    conviction: int
    headline: str
    thesis: str
    strengths: list | None = None
    risks: list | None = None
    conditions: list | None = None


class PreviewOut(BaseModel):
    company: CompanyOut
    objectives: list[ObjectiveOut]
    org: OrgChartOut
    cost_estimate_cents: int | None = None
    investment_reviews: list[InvestmentReviewOut] = Field(default_factory=list)


# ── API keys ─────────────────────────────────────────────────────────────────
class ApiKeyCreateRequest(BaseModel):
    provider: str = "anthropic"
    api_key: str = Field(min_length=8)


class ApiKeyOut(ORMModel):
    id: uuid.UUID
    provider: str
    key_fingerprint: str
    status: str


# ── Budget ───────────────────────────────────────────────────────────────────
class BudgetOut(ORMModel):
    id: uuid.UUID
    limit_cents: int
    spent_cents: int
    reserved_cents: int
    currency: str


class BudgetView(BaseModel):
    budget: BudgetOut
    by_category: dict[str, int]
    by_agent: dict[str, int]


class BudgetPatchRequest(BaseModel):
    limit_cents: int = Field(gt=0)


# ── Tasks / runs ─────────────────────────────────────────────────────────────
class TaskOut(ORMModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    parent_task_id: uuid.UUID | None
    depth: int
    goal: str
    status: str
    cost_cents: int
    output: dict | None
    created_at: datetime


# ── Governance ───────────────────────────────────────────────────────────────
class PolicyOut(ORMModel):
    id: uuid.UUID
    name: str
    enabled: bool
    scope: str
    rule: dict
    effect: str
    priority: int


class PolicyCreateRequest(BaseModel):
    name: str
    scope: str = "global"
    rule: dict
    effect: str
    priority: int = 100
    enabled: bool = True


class BreakerOut(ORMModel):
    id: uuid.UUID
    type: str
    state: str
    tripped_reason: str | None


class ReputationOut(ORMModel):
    agent_id: uuid.UUID
    trust: float
    accuracy: float
    roi: float
    reliability: float
    sample_count: int


class DecisionOut(ORMModel):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    task_id: uuid.UUID | None
    kind: str
    summary: str
    status: str
    created_at: datetime


# ── Memory / Copilot ─────────────────────────────────────────────────────────
class MemoryOut(ORMModel):
    id: uuid.UUID
    type: str
    title: str
    content: str
    created_at: datetime


class CopilotAskRequest(BaseModel):
    question: str


class CopilotAskResponse(BaseModel):
    answer: str
    kind: str  # "query" | "command"


# ── Marketplace ──────────────────────────────────────────────────────────────
class AgentListingOut(ORMModel):
    id: uuid.UUID
    name: str
    role: str
    description: str
    provider: str
    price_cents: int
    trust: float | None = None
    accuracy: float | None = None
    roi: float | None = None
    reliability: float | None = None


class HireAgentRequest(BaseModel):
    listing_id: uuid.UUID
