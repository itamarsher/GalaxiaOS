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
    email_from: str | None = None


class CompanyUpdateRequest(BaseModel):
    """Founder-editable company settings. Fields left unset are not changed."""

    # Sender ("From:") address agents send mail as, e.g. ``Acme <hello@acme.com>``
    # or ``hello@acme.com``. Empty string clears it (falls back to the global
    # default). Validated loosely — it must contain an ``@`` — so display names
    # and angle-bracket forms are accepted.
    email_from: str | None = Field(default=None, max_length=320)


class PlaybookOut(BaseModel):
    """The company's global operating playbook (the system prompt every agent gets)."""

    playbook: str  # the effective text (custom if set, else the platform default)
    customized: bool  # True once the founder/CEO has overridden the default
    default: str  # the platform default, so the UI can offer "reset"


class PlaybookUpdateRequest(BaseModel):
    # The full new playbook. Empty string clears the override (reverts to default).
    playbook: str = Field(max_length=8000)


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
    # The agent's launch prompt, surfaced so the founder can see how each agent is
    # directed: ``system_prompt`` is the agent's company-specific directive (editable
    # by the CEO); ``role_description`` is the fixed behaviour for its role.
    system_prompt: str = ""
    role_description: str = ""


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


# ── Sites & connected domains ────────────────────────────────────────────────
class SiteDomainOut(ORMModel):
    id: uuid.UUID
    domain: str
    status: str


class SiteOut(ORMModel):
    id: uuid.UUID
    slug: str
    title: str
    status: str
    deployment_url: str | None = None
    created_at: datetime
    domains: list[SiteDomainOut] = []
    cost_estimate_cents: int | None = None
    investment_reviews: list[InvestmentReviewOut] = Field(default_factory=list)


class GenerationEvent(BaseModel):
    ts: float
    label: str
    pct: int


class GenerationProgressOut(BaseModel):
    phase: str
    pct: int
    message: str
    status: str  # "idle" | "running" | "done" | "error"
    error: str | None = None
    events: list[GenerationEvent] = Field(default_factory=list)


class RefineRequest(BaseModel):
    message: str = Field(min_length=1)


class RefineResponse(BaseModel):
    reply: str
    preview: PreviewOut


# ── API keys ─────────────────────────────────────────────────────────────────
class ApiKeyCreateRequest(BaseModel):
    provider: str = "anthropic"
    api_key: str = Field(min_length=8)


class ApiKeyOut(ORMModel):
    id: uuid.UUID
    provider: str
    key_fingerprint: str
    status: str


# ── Integrations (Cloudflare site host + DNS) ────────────────────────────────
class CloudflareCredsRequest(BaseModel):
    api_token: str = Field(min_length=8)
    account_id: str = Field(min_length=8)


class CloudflareStatusOut(BaseModel):
    configured: bool
    account_id: str | None = None


# ── Integrations (Google Drive file store) ───────────────────────────────────
class GoogleDriveCredsRequest(BaseModel):
    """The OAuth bundle a founder pastes to connect their personal Drive.

    All three are required; ``root_folder_id`` is optional and defaults to the
    Drive root ("root"). The whole bundle is stored envelope-encrypted and never
    returned.
    """

    client_id: str = Field(min_length=8)
    client_secret: str = Field(min_length=8)
    refresh_token: str = Field(min_length=8)
    root_folder_id: str | None = None


class GoogleDriveStatusOut(BaseModel):
    configured: bool
    root_folder_id: str | None = None


class CompanyFileOut(ORMModel):
    id: uuid.UUID
    category: str
    name: str
    description: str | None = None
    mime_type: str
    folder_path: str
    web_url: str | None = None
    size_bytes: int | None = None
    created_at: datetime


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


class TaskDetailOut(TaskOut):
    agent_name: str | None = None
    agent_role: str | None = None
    input: dict | None = None
    children: list[TaskOut] = Field(default_factory=list)
    pending_decision: "DecisionOut | None" = None


class TaskTranscriptOut(BaseModel):
    """A live tail of a running task's working memory (last N rendered lines)."""

    task_id: uuid.UUID
    status: str
    lines: list[str] = Field(default_factory=list)


# ── Budget detail ────────────────────────────────────────────────────────────
class SpendEntryOut(ORMModel):
    id: uuid.UUID
    category: str
    amount_cents: int
    vendor: str | None = None
    sku: str | None = None
    description: str | None = None
    task_id: uuid.UUID | None = None
    created_at: datetime


class AgentSpendOut(BaseModel):
    agent_id: uuid.UUID | None
    agent_name: str | None = None
    agent_role: str | None = None
    total_cents: int
    entries: list[SpendEntryOut] = Field(default_factory=list)


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
    agent_name: str | None = None
    agent_role: str | None = None
    trust: float
    accuracy: float
    roi: float
    reliability: float
    sample_count: int


class DecisionOut(ORMModel):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_name: str | None = None
    agent_role: str | None = None
    task_id: uuid.UUID | None
    kind: str
    summary: str
    status: str
    created_at: datetime
    # Bigger-picture context, attached at read time (see decisions API _to_out).
    task_goal: str | None = None  # the ask that triggered this decision
    initiative: str | None = None  # the higher-level initiative it belongs to
    objective_title: str | None = None  # best-effort related objective


class DecisionChatTurn(BaseModel):
    """One turn of a founder↔agent decision discussion."""

    who: str  # "you" (founder) | "agent"
    text: str


class DecisionChatRequest(BaseModel):
    message: str = Field(min_length=1)


class DecisionChatThread(BaseModel):
    """The persisted discussion thread for a decision, oldest turn first."""

    thread: list[DecisionChatTurn] = Field(default_factory=list)


class DecisionChatResult(DecisionChatThread):
    """A chat reply plus the full updated thread (the server is the source of truth)."""

    answer: str


class DecisionResolveRequest(BaseModel):
    note: str | None = None


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


# Resolve the forward reference from TaskDetailOut -> DecisionOut.
TaskDetailOut.model_rebuild()
