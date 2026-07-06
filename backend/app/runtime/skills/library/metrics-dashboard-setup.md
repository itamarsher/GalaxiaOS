---
name: metrics-dashboard-setup
title: Metrics Dashboard Setup
description: Build a focused dashboard of the few metrics that actually drive decisions, not a wall of charts.
roles: data, ceo
---
# Metrics Dashboard Setup

A dashboard should answer 'how are we doing and what needs attention' at a glance. This playbook
builds a focused one — the few decision-driving metrics, defined consistently — not a data wall.

## Workflow
1. **Start from the decisions.** Which recurring decisions should this dashboard inform (health check,
   OKR tracking, spend)? Metrics that don't inform a decision are clutter. `write_memory` (type `experiment`).
2. **Pick the vital few.** Choose the handful of metrics that actually indicate health — a north-star plus
   its key drivers. Tie them to OKRs (`company-okr-planning`). Twenty metrics means no focus.
3. **Define each metric precisely.** Exact formula, source, and time window (`kpi-definition`). An
   ambiguous metric produces arguments, not decisions. Document definitions alongside the numbers.
4. **Add context, not just values.** Each metric needs a comparison — target, prior period, or trend.
   A number with no reference point can't be judged good or bad.
5. **Wire it to real data.** `read_metrics` / `read_financials` as sources; ensure freshness and that
   the numbers reconcile with the source of truth (`data-quality-audit`). A wrong dashboard is worse than none.
6. **Publish and maintain.** `create_report` (kind `status_report`) or a living view; review that each
   metric still earns its place. `write_memory` (type `learning`) metrics that turned out not to matter.

## Decision framework — signal over comprehensiveness
Include a metric only if someone would act differently based on it. A focused dashboard people actually
use beats a comprehensive one they ignore. When adding a metric, consider removing one.

## Definition of done
- Tied to real decisions/OKRs; a vital-few metric set, each precisely defined with a comparison.
- Wired to reconciled real data; published and pruned over time.

## Common failure modes
- **Data walls.** So many charts nobody can see what matters.
- **Undefined metrics.** Ambiguous formulas breed disputes instead of decisions.
- **No context.** Bare numbers with no target or trend can't be judged.
