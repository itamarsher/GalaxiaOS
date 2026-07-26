# RFC 0002 — Function-first: pick the functions, GalaxiaOS runs the improvement cycle

- **Status:** Draft (for discussion). Slice 1 lands with this RFC.
- **Scope:** The founder-facing operating model + the continuous per-function
  improvement loop. Builds on RFC 0001 (functions as worker-agnostic slots).

## Summary

Every business of the same shape has the same building blocks: a website, social,
outbound and inbound demand, a brand, customer service, legal, finance, billing.
Today a founder gives a mission + budget and gets an **opaque, LLM-designed fleet
of agents**. RFC 0001 made a *function* a first-class slot internally, but the
founder never gets to *name the functions they want*, and improvement is a
per-cycle retrospective, not a loop driven by real status. Two changes:

1. **Function-first onboarding.** The founder **picks the functions** to implement
   and auto-improve from a catalog of building blocks. The mission→plan LLM
   **recommends** a starting set (`recommended_functions`); the founder toggles from
   there. GalaxiaOS **spins up each one's components** — staffing agent, seed skills,
   and the KRs that define its health — through the *existing* provisioning path.
2. **A continuous, status-driven improvement cycle.** A loop that, per function,
   reads the company's **real signals** for that function's health and drives the
   next improvement, learning **across companies** what actually improves it.

**Tenet — in-house first.** A function is `in_house` by default: GalaxiaOS builds
and runs it with its own agents + native tools, so a founder is **not** forced to
register for a dozen third-party services. Only genuinely-hard functions are
`external` and need a connected provider — billing/payments is the archetype
(Stripe). In-house blocks seed capability *playbooks*, not SaaS connectors.

## 1. The building blocks — `services/function_catalog.py` (slice 1, this PR)

A declarative catalog. Each `BusinessFunction` maps a block to: the `AgentRole`
that staffs it (`custom` for finer-grained blocks, so several coexist —
`provision_fleet` never dedupes `custom`), its `implementation` (`in_house` |
`external`), a `provision_fleet`-shaped spec (`spec_for`), seed skill playbooks, and
the **health signals** that define it improving. It maps only onto *existing* roles
(a new `AgentRole` is a migration). `resolve_selection(keys)` turns picks into
provision specs and **always appends the guaranteed oversight blocks** (CEO,
governance, auditor, data, platform), so any selection still launches a governed
company. `GET /functions/catalog` exposes it (`api/functions.py`).

## 2. Function-first onboarding (slice 2 — backend landed)

**Landed:** the mission→plan LLM now emits `recommended_functions`
(`recommendation_directive` appends the catalog vocabulary, in-house-first). When a
mission recommends any selectable block, `generate` provisions the fleet from the
catalog via `provision_fleet(specs=resolve_selection(picked), …)` — one path,
oversight guaranteed, **no second org-design LLM call** — and each function-agent
carries its identity + health target in `Agent.config` (JSONB, no migration) with
the health signals baked into its system prompt. `external` picks (billing) are
returned as `functions_needing_connection` for the connect-prompt; in-house blocks
need nothing. No recommendation → today's LLM org designer (additive, not a cutover).

**Slice 2b landed:** the founder-facing picker. `POST /onboarding/{id}/functions`
(`onboarding.set_functions`) reconciles the draft's function-agents to the picks —
adds the newly-picked blocks, removes deselected ones (never core/oversight), and
re-splits the budget; the provisioned function-agents *are* the persisted, editable
selection (`PreviewOut.functions`). The onboarding review UI renders the catalog with
the recommendations pre-checked and `external` picks flagged to connect. Seeding
formal `KeyResult` rows from `health_signals` still waits on real targets (today the
target lives on the agent + drives slice 3).

## 3. The continuous per-function improvement cycle (slice 3 — landed)

`services/function_improvement.py` generalizes the retrospective into a
**status-driven, per-function** loop. Each cycle, `assess_functions` reads — off
each function-agent's `config` — which of its `health_signals` the company has
**actually measured** (real `MetricSignal` rows) vs. is flying blind on, and
`improvement_brief` turns the gaps into a CEO brief. The hourly `improve_functions`
cron (opt-in, `function_improvement_enabled`) hands that brief to
`orchestrator.create_improvement_run` for an **idle** company with off-track
functions, so the moves dispatch through the normal governed path (objective-tagged,
budgeted, approval-gated) — not around it. The scoring is deliberately grounded in
real data: an unmeasured KPI is the unambiguous first gap ("you can't improve what
you don't track"); off-target detection against seeded targets slots into
`classify` next. Skill-playbook edits and `request_capability` remain available
moves the CEO can take from the brief.

## 4. Cross-company learning (slice 4)

The dogfooding loop (`MISSION.md`) turns any agent's unmet need into a shipped
platform capability for every company. This extends it to *function performance*:
which moves actually lifted a signal (e.g. `signup_conversion_rate`), aggregated
across companies (tenant-isolated data, shared *learning*) and propagated as
skill-library edits via `skill-optimize` so `default_skills` keep improving.
