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

## 2. Function-first onboarding (slice 2)

Add a **function-selection** step: render the catalog, pre-check the LLM's
`recommended_functions`, let the founder toggle. Launch provisions via
`provision_fleet(specs=resolve_selection(keys), …)` — one path, oversight
guaranteed — and **seeds each function's health KRs** from `health_signals`. Only
`external` blocks prompt to connect a provider (via `is_in_house`); in-house blocks
need nothing. No selection → today's LLM-designed fleet: additive, not a cutover.

## 3. The continuous per-function improvement cycle (slice 3)

Generalizes the retrospective (`orchestrator._maybe_continue_cycle`) and the
skill-optimizer into a **status-driven, per-function** loop. Each cycle, per
function, it reads the real signals for its `health_signals` (`services/metrics`)
plus objective/KR progress (`services/objectives`) and reputation; off-target, it
drives the highest-leverage move — a `Task`, a skill-playbook edit
(`runtime/skill_optimizer`), or `request_capability` (`services/feature_requests`).
Only the scheduler is new; actions flow through existing budget + governance gates.

## 4. Cross-company learning (slice 4)

The dogfooding loop (`MISSION.md`) turns any agent's unmet need into a shipped
platform capability for every company. This extends it to *function performance*:
which moves actually lifted a signal (e.g. `signup_conversion_rate`), aggregated
across companies (tenant-isolated data, shared *learning*) and propagated as
skill-library edits via `skill-optimize` so `default_skills` keep improving.
