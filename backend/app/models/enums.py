"""Enumerations shared across the data model."""

from __future__ import annotations

import enum


class CompanyStatus(str, enum.Enum):
    draft = "draft"
    launching = "launching"
    active = "active"
    paused = "paused"
    halted = "halted"


class MembershipRole(str, enum.Enum):
    founder = "founder"
    admin = "admin"


class AgentRole(str, enum.Enum):
    ceo = "ceo"
    growth = "growth"
    research = "research"
    product = "product"
    finance = "finance"
    governance = "governance"
    auditor = "auditor"
    custom = "custom"


class AutonomyLevel(str, enum.Enum):
    suggest = "suggest"
    approve_required = "approve_required"
    autonomous = "autonomous"


class AgentStatus(str, enum.Enum):
    active = "active"
    paused = "paused"


class AgentBackendType(str, enum.Enum):
    native = "native"
    external = "external"
    marketplace = "marketplace"


class AgentSource(str, enum.Enum):
    generated = "generated"
    hired = "hired"


class EdgeRelation(str, enum.Enum):
    reports_to = "reports_to"
    collaborates = "collaborates"
    escalates_to = "escalates_to"


class RunTrigger(str, enum.Enum):
    onboarding = "onboarding"
    scheduled = "scheduled"
    founder_command = "founder_command"
    agent_dispatch = "agent_dispatch"


class RunStatus(str, enum.Enum):
    running = "running"
    done = "done"
    failed = "failed"


class TaskStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    waiting_approval = "waiting_approval"
    done = "done"
    failed = "failed"
    blocked = "blocked"


class SpendCategory(str, enum.Enum):
    llm = "llm"
    tool = "tool"
    external = "external"
    agent_invocation = "agent_invocation"


class BudgetPeriod(str, enum.Enum):
    monthly = "monthly"
    total = "total"


class PolicyEffect(str, enum.Enum):
    allow = "allow"
    deny = "deny"
    require_approval = "require_approval"


class PolicyScope(str, enum.Enum):
    global_ = "global"
    agent = "agent"
    category = "category"


class BreakerType(str, enum.Enum):
    spend = "spend"
    loop = "loop"
    rate = "rate"
    risky_action = "risky_action"


class BreakerState(str, enum.Enum):
    armed = "armed"
    tripped = "tripped"


class MemoryType(str, enum.Enum):
    decision = "decision"
    experiment = "experiment"
    result = "result"
    learning = "learning"
    strategy_shift = "strategy_shift"


class DecisionKind(str, enum.Enum):
    spend_approval = "spend_approval"
    risky_action = "risky_action"
    strategy = "strategy"
    plan_approval = "plan_approval"


class DecisionStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class ApiKeyStatus(str, enum.Enum):
    active = "active"
    revoked = "revoked"


class MetricSource(str, enum.Enum):
    """Where a real-world outcome signal came from."""

    founder = "founder"  # entered by the human founder
    agent = "agent"  # recorded by an agent via a tool
    integration = "integration"  # pulled from an external system
    simulated = "simulated"  # synthetic/dev signal


class InvestorPersona(str, enum.Enum):
    """The three onboarding investor reviewers."""

    small_business = "small_business"  # pragmatic, cash-flow / lifestyle-business lens
    startup = "startup"  # VC / venture-scale lens
    devils_advocate = "devils_advocate"  # the nay-sayer; argues the bear case


class InvestmentStance(str, enum.Enum):
    """An investor's bottom-line verdict."""

    invest = "invest"
    conditional = "conditional"
    pass_ = "pass"
