# RFC 0002 — Function-first: pick the functions, GalaxiaOS runs the improvement cycle

- **Status:** Draft (for discussion). Slice 1 lands with this RFC.
- **Scope:** The founder-facing operating model + the continuous per-function
  improvement loop. Builds on RFC 0001 (functions as worker-agnostic slots).

## Summary

Every business of the same shape has the same building blocks: a website, social,
outbound and inbound demand, a brand, customer service, legal, finance, product,
research. Today a founder gives a mission + budget and gets an **opaque,
LLM-designed fleet of agents** back. RFC 0001 made a *function* a first-class
worker-agnostic slot internally — but the founder never gets to *name the functions
they want*, and improvement is a per-cycle retrospective, not a loop driven by each
function's real status.

This RFC makes two changes:

1. **Function-first onboarding.** The founder **picks the functions** to implement
   and auto-improve from a catalog of building blocks (recommended from the
   mission). GalaxiaOS **spins up each one's components** — the staffing agent, its
   seed skills, and the KRs that define its health — through the *existing*
   provisioning path.
2. **A continuous, status-driven improvement cycle.** GalaxiaOS owns a loop that,
   per function, reads the company's **real signals** for that function's health,
   compares them to target, and drives the next improvement, learning **across
   companies** which moves actually improve a given function.

The differentiator stays the same (RFC 0001): Galaxia owns the business — org,
objectives, budget, governance, memory. This RFC changes the *input* (pick
functions, not agents) and closes the *output* (own the improvement loop).

## 1. The building blocks — `services/function_catalog.py` (slice 1, this PR)

A declarative catalog. Each `BusinessFunction` maps a building block to: the
existing `AgentRole` that staffs it (`custom` for finer-grained blocks, so several
coexist — `provision_fleet` never dedupes `custom`), a founder-facing summary, a
`provision_fleet`-shaped spec (`spec_for`), seed skill playbooks, and the **health
signals** that define the block improving (`health_signals`). It maps only onto
*existing* roles on purpose (a new `AgentRole` is a migration).
`resolve_selection(keys)` turns picks into provision specs and **always appends the
guaranteed oversight blocks** (CEO, governance, auditor, data, platform), so any
selection still launches a governed company. `GET /functions/catalog` exposes it
to the picker (`api/functions.py`). This is the seam both halves below build on.

## 2. Function-first onboarding (slice 2)

An explicit **function-selection** step: render the catalog, recommend a starting
set from the mission (the `MISSION_TO_PLAN` call already reasons about what the
business needs — have it emit `recommended_functions: [key]` against the catalog
vocabulary), and let the founder toggle blocks on/off. Launch then provisions via
`provision_fleet(specs=resolve_selection(keys), …)` — one code path, oversight
guaranteed as today — and **seeds each function's health KRs** from
`health_signals` so its improvement target is concrete from day one. With no
explicit selection, generation falls back to today's LLM-designed fleet: the
catalog is additive, not a hard cutover.

## 3. The continuous per-function improvement cycle (slice 3)

Generalizes the end-of-cycle retrospective (`orchestrator._maybe_continue_cycle`)
and the skill-optimizer into a **status-driven, per-function** loop. Each cycle,
for every function, it reads the company's real signals for that function's
`health_signals` (`services/metrics`) plus objective/KR progress
(`services/objectives`) and reputation (`services/reputation`); when a signal is
off-target or stalled it drives the highest-leverage move — dispatch an
improvement initiative (a `Task`), open a skill-playbook edit
(`runtime/skill_optimizer`), or `request_capability` (`services/feature_requests`)
for a platform gap. The new part is just the scoring scheduler; every action still
flows through the existing budget + governance chokepoints, so nothing here spends
or acts unmetered.

## 4. Cross-company learning (slice 4)

The dogfooding loop (`MISSION.md`) already turns any agent's unmet need into a
shipped platform capability for every company. This extends it to *function
performance*: which playbook edits / initiative shapes actually moved
`signup_conversion_rate` for `website` or `outbound_reply_rate` for `outbound`,
aggregated across every company running that function (tenant-isolated data,
shared *learning*). Winning moves propagate as skill-library edits via the
`skill-optimize` pipeline, so a block's `default_skills` keep getting better.

## 5. Migration plan (each slice shippable)

1. **The catalog + read API** — no behaviour change. **← this PR.**
2. **Function-first onboarding** — recommend + select; provision via
   `resolve_selection`; seed health KRs. Falls back to today's flow when unset.
3. **The per-function improvement cycle** — a scheduler that scores each function
   against its `health_signals` and drives the next move through existing paths.
4. **Cross-company function learning** — aggregate which moves improved which
   signals; propagate winners via `skill-optimize`.

## 6. Open questions

Recommendation strength (mission pre-selects starter functions vs. a blank menu);
signal capture (auto-wired from connected integrations — analytics, CRM, Stripe —
vs. agent-reported); off-target thresholds before the cycle acts on a stalled
signal.
