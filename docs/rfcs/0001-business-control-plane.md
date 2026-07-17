# RFC 0001 — Galaxia as the business control plane; agents connect in

- **Status:** Draft (for discussion)
- **Scope:** Architecture direction. No code changes in this PR.
- **Supersedes:** nothing yet. Establishes the target for the runtime layer.

## Summary

Today Galaxia does two very different jobs, and only one of them is
differentiated:

- **Job A — the business brain (differentiated).** Turn a *mission + budget* into
  a *designed org*: objectives/KRs, the right functions, budget discipline,
  governance/approvals, cross-function coordination, institutional memory, and the
  founder-as-board-member control loop.
- **Job B — the agent runtime (undifferentiated treadmill).** A think→act loop,
  tool calling, tool discovery, an MCP client, vector memory, context compaction.
  Claude Code, OpenClaw, Codex and others already do this well and improve weekly.

This RFC proposes we **stop owning Job B** and reframe Galaxia as a **business
control plane that external agent runtimes connect *into*** over MCP. An agent
boots, connects to Galaxia to fetch its **mandate** (which function it is, the
mission, its objectives, budget envelope, current state) and its **next
initiative**, does the work with *its own* capabilities, and **reports results
back**. Galaxia keeps what's hard and unique — the org design, governance, budget,
coordination, and institutional memory — and delegates the runtime to
best-in-class agent harnesses.

We evaluated **OpenClaw** (`openclaw/openclaw`, MIT) as the reference external
runtime and found it a strong fit (see [§7](#7-reference-runtime-openclaw)).

## Motivation

1. **We are reinventing plumbing we can't win at.** `runtime/backends/native.py`
   is a full agent harness — perceive → think → act, tool discovery
   (`discover_tools`/`use_tool`), an MCP client, budget-aware retries, transcript
   compaction. Every week that Claude Code / OpenClaw / Codex improve, our
   in-house loop falls further behind at a job that isn't our product.
2. **Our recent dogfooding pain was Job B, not Job A.** The competence fixes
   (#170/#171), the publish-HTML bug (#172), the media-quota surfacing (#173), and
   the `dispatch_task` "product agent acting as designer" routing gap were all
   runtime-plumbing problems. The *business* layer (objectives, governance,
   budget) behaved.
3. **The mission already commits to this seam.** `MISSION.md` names `AgentBackend`
   ("how an agent executes") and `LLMProvider` as decoupling seams so "the free
   core never traps you in a single vendor or a single way of running agents."
   This RFC leans into a seam we already declared, rather than inventing one.
4. **It unlocks "import an existing business."** If functions are external agents
   (or people) that bind to Galaxia's function slots, then onboarding an
   *existing* operation is the same protocol as launching a new one — you don't
   rebuild their tooling, you give them the objectives/governance/coordination
   layer on top.

## Goals

- Galaxia owns the **business**: org design, objectives/KRs, initiatives, budget
  envelopes, governance/approvals, coordination, institutional memory,
  multi-tenant isolation.
- Any MCP-capable agent runtime can be a business function by connecting to a
  Galaxia **Business-Function MCP server** with a per-`(company, function)`
  identity.
- Preserve the **"mission + budget → running business the same day"** promise for
  non-technical founders.
- Preserve **founder control**: money, data access, and irreversible calls stay
  gated by Galaxia governance regardless of which runtime executes.

## Non-goals

- Rewriting the onboarding generator (mission → objectives → org). That is the
  crown jewel and stays.
- Ripping out `NativeBackend` in one step. It becomes the default *client* of the
  new API (see [§5](#5-runtime-binding-preserving-the-same-day-promise)).
- Building our own agent harness features (better memory, tool discovery, etc.).
  The opposite: we delete that surface over time.

## 1. The reframe

```
            ┌──────────────────────── GALAXIA (control plane) ────────────────────────┐
            │  mission→org generator · objectives/KRs · initiative queue · governance   │
            │  budget envelopes · decisions/approvals · institutional memory · tenancy   │
            │                                                                            │
            │                    Business-Function MCP server  (remote, per-tenant)      │
            └───────▲───────────────────────▲───────────────────────────▲──────────────┘
                    │ MCP (streamable-HTTP)  │                           │
        ┌───────────┴──────────┐  ┌──────────┴───────────┐   ┌───────────┴──────────┐
        │ OpenClaw agent       │  │ Built-in runtime      │   │ Founder's own agent   │
        │  = "Growth" function │  │  (managed OpenClaw or │   │  (Claude Code /       │
        │  own tools+memory    │  │   NativeBackend)      │   │   OpenClaw / custom)  │
        └──────────────────────┘  └──────────────────────┘   └──────────────────────┘
```

Galaxia becomes an **MCP server** (the inverse of today, where it is an MCP
*client*). Agents bring their own reasoning, tools, connectors, and how-to memory.
Galaxia owns what to work on, who owns it, what it costs, what's allowed, what's
true, and what the company has learned.

## 2. The Business-Function MCP surface

A small, powerful toolset served by Galaxia to a connected agent. Names are
illustrative; the shape is the point.

| Tool | Purpose |
|---|---|
| `get_mandate()` | "You are the **Growth** function for Company X." Mission, your objectives + KRs, budget envelope, constraints, brand, current metrics. |
| `get_next_initiative()` | The next prioritized initiative for your function (with its budget envelope + acceptance criteria). |
| `report_result(initiative, outcome, artifacts, spend)` | Close the loop; Galaxia updates state, records spend, routes to audit. |
| `get_business_state()` | Current state of the company + your function. |
| `coordinate_with(function, message)` / `post_update(text)` | Cross-function messaging + the founder-facing mission log. |
| `request_decision(kind, payload)` / `request_budget(cents, reason)` | Escalate to the founder. **Governance & budget stay in Galaxia.** |
| `record_metric(...)` / `write_institutional_memory(...)` | Durable, cross-agent business memory + KR telemetry. |

These map onto services that already exist: `services/objectives.py`,
`services/runs.py` (initiatives/tasks), `services/budget.py` +
`runtime/cost_meter.py`, `services/decisions.py`, `services/governance.py`,
`services/memory.py`. The MCP server is a **new transport over existing business
logic**, not new business logic.

## 3. The `AgentBackend` seam already supports this

`runtime/backends/__init__.py` defines:

```python
class AgentBackend(Protocol):
    async def run(self, ctx: RuntimeContext, agent: Agent, task: Task) -> dict: ...

def get_backend(backend_type: str) -> AgentBackend: ...
```

There are **already two implementations**: `NativeBackend` (in-process loop) and
`MarketplaceBackend`, which "runs a *hired* agent … the remote execution itself
[happens elsewhere] while the org chart treats hired agents identically." So
**"execution happens outside Galaxia" is already a supported shape.** This RFC
adds a third backend — call it `ConnectedBackend` — whose `run()` doesn't execute
a loop at all: it **offers the initiative** to a bound external runtime and awaits
a `report_result`. The task lifecycle becomes *offered → claimed → in-progress →
reported → audited* rather than an in-process think→act.

## 4. Capability brokering & the budget model (the load-bearing decision)

Today `CostMeter` (`runtime/cost_meter.py`) reserves budget **before every LLM
token** and every external charge — a hard chokepoint. If agents run on their own
runtime with their own provider keys, **Galaxia never sees those tokens**, so
per-token metering goes away. Budget enforcement moves up a level:

- **Initiative-level envelopes.** Each `get_next_initiative()` carries a spend
  cap; the agent works within it and returns `spend` in `report_result`.
- **Broker only money-touching capabilities.** Keep Galaxia-brokered (and
  metered) the things that spend real external money — media generation, ads,
  domains, paid data — via the existing `metered_external` path. Let the rest
  (files, web, generic tools) be the agent's own.
- **Audited self-report.** Reported spend is reconciled against brokered charges
  and the governance reputation signal; large or anomalous self-reports escalate.

**Decision required:** we trade a token-level chokepoint for a cleaner
architecture and a coarser (envelope-level) budget guarantee. This also answers
the earlier "capability brokering" question: *money-touching capabilities stay
Galaxia-brokered; everything else is the agent's.*

## 5. Runtime binding — preserving the "same-day" promise

Two user classes, one protocol:

- **Non-technical founder (zero setup):** Galaxia provides a **default hosted
  runtime** that auto-binds to the function slots — a **managed OpenClaw Gateway**
  (or, transitionally, today's `NativeBackend`). Batteries included; nothing to
  configure.
- **Power user / existing business:** point your own OpenClaw / Claude Code agent
  at the same Galaxia MCP endpoint with a per-function token.

The key move that protects the same-day promise: **the built-in runtime is just
the first, most-tested client of the same Business-Function MCP API** — we dogfood
our own protocol. If it's awkward for us, it's awkward for everyone.

## 6. Multi-tenancy

OpenClaw isolates at the **persona/workspace** level within one Gateway — not a
company boundary. Tenancy stays Galaxia's responsibility:

- The MCP server is **per-tenant scoped** by the connection token; every tool call
  is authorized against `(company, function)` and RLS as today.
- For the managed runtime, isolate at the **Gateway-per-tenant** (or
  pool-per-tenant) level. External agents are inherently the founder's own
  boundary.

## 7. Reference runtime: OpenClaw

Full scoping in the appendix. Summary of fit against Job B:

| Need | OpenClaw | Evidence |
|---|---|---|
| MCP **client** → our remote server | ✅ `mcp.servers.<name>`, **streamable-HTTP/SSE/stdio**, bearer/OAuth/mTLS, per-agent routing | docs `/cli/mcp` |
| Headless / worker drive | ✅ `openclaw agent --json`, `POST /v1/chat/completions`, `POST /hooks/agent` | docs `/cli/agent`, `/gateway/openai-http-api` |
| Scheduling = "check-in" model | ✅ cron + `isolated` runs + **`webhook` result delivery** | docs `/automation/cron-jobs` |
| Memory | ✅ per-agent Markdown + vector `memory_search`, pluggable backends | docs `/concepts/memory` |
| Multi-agent identity | ✅ agent = persona scope (workspace/model/sessions/sandbox) + `bindings` | docs `/concepts/multi-agent` |
| BYOK providers + failover | ✅ Anthropic/OpenAI/Gemini/local + ~30 more, auth-profile rotation | docs `/concepts/model-providers` |

**What it brings beyond plumbing:** a skills/ClawHub + plugin-SDK ecosystem;
~25 messaging channels with routing (a founder DM to "the marketing agent" becomes
trivial); sandboxing + provider failover + operational HITL/tool-policy.

**Confirmed gaps = our layer:** no OKRs/mandate model, **no native budget
metering/enforcement** (open issue #58826), no business-level approval/governance,
no org design, no cross-agent institutional memory, isolation ≠ multi-tenancy.
Exactly the split this RFC relies on.

**Risks:** (1) validate the MCP-tool→model path inside an *embedded* OpenClaw
turn before committing; (2) multi-tenancy is Gateway-per-tenant; (3) we take on
Gateway lifecycle + version churn of a large, fast-moving monorepo.

## 8. Migration plan (incremental)

1. **Define the Business-Function MCP surface** ([§2](#2-the-business-function-mcp-surface))
   as a first-class server over existing services. No user-visible change.
2. **Re-point `NativeBackend` to consume that API** instead of reaching into
   services directly. Proves the protocol against our own runtime.
3. **Add `ConnectedBackend`** + a "connect your own agent" flow (per-function
   token + a template OpenClaw/Claude Code config). First external function goes
   live behind a flag.
4. **Ship the managed OpenClaw Gateway** as the default hosted runtime; make it
   the batteries-included binding.
5. **Thin the core:** migrate capability tools out to agent-side; keep only
   business-state tools in Galaxia. Retire the in-house discovery/compaction
   surface.

Each step is shippable and reversible; no big-bang cutover.

## 9. Security considerations

- **Per-function tokens** are tenant-scoped credentials; every MCP tool call is
  authorized against `(company, function)` + RLS. Token compromise is blast-radius
  limited to one function of one company.
- **The BYOK secret boundary is unchanged** for anything Galaxia still brokers
  (envelope encryption per `MISSION.md`). Agent-owned provider keys leave our
  custody entirely — a *reduction* in secrets we hold.
- **Governance is enforced server-side**, never in the agent: an agent can
  `request_decision`, but only Galaxia (and the founder) can resolve one.

## 10. Open questions / decisions needed

1. **Budget guarantee** — accept envelope-level enforcement + audited self-report
   in exchange for losing the token-level chokepoint? ([§4](#4-capability-brokering--the-budget-model-the-load-bearing-decision))
2. **Protocol surface** — MCP-only, or also a plain REST/webhook API for runtimes
   that don't speak MCP? (MCP-first recommended; OpenClaw + Claude Code both speak
   it.)
3. **Default hosted runtime** — managed OpenClaw Gateway from the start, or keep
   `NativeBackend` as the default until the OpenClaw path is proven?
4. **Multi-tenant model for the managed runtime** — Gateway-per-tenant vs
   pool-with-workspace-isolation.

## 11. Alternatives considered

- **Keep and invest in `NativeBackend`.** Rejected: it's the undifferentiated
  treadmill; we lose ground weekly and it's the source of most recent bugs.
- **Adopt a different runtime (Claude Code / Codex) as primary.** Not exclusive —
  the MCP contract is runtime-agnostic; OpenClaw is the *reference* because it's
  MIT, self-hostable as a Gateway service, MCP-native, and multi-agent. Claude
  Code remains a first-class client for power users.
- **Embed Galaxia as an OpenClaw plugin** (rather than an external MCP server).
  Rejected: the plugin SDK "assumes hosted Gateway infrastructure" and would
  invert ownership; keeping Galaxia as the control plane the agent connects *out*
  to preserves the tenancy/governance boundary.

## Appendix: OpenClaw evaluation sources

- MCP client / transports / auth — `docs.openclaw.ai/cli/mcp`
- Headless agent drive — `docs.openclaw.ai/cli/agent`,
  `docs.openclaw.ai/gateway/openai-http-api`
- Scheduling / webhooks — `docs.openclaw.ai/automation/cron-jobs`
- Memory — `docs.openclaw.ai/concepts/memory`
- Multi-agent — `docs.openclaw.ai/concepts/multi-agent`
- Providers / failover — `docs.openclaw.ai/concepts/model-providers`
- Budget gap — `github.com/openclaw/openclaw/issues/58826`
- License — MIT (`github.com/openclaw/openclaw`)
