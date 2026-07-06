---
name: kpi-definition
title: KPI Definition
description: Define each key metric unambiguously — formula, source, and window — so numbers are trusted and comparable.
roles: data, finance
---
# KPI Definition

Most metric disputes are definition disputes. This playbook pins down each KPI precisely so the whole
fleet computes it the same way and the numbers are trusted and comparable over time.

## Workflow
1. **Name the KPI and its purpose.** What decision or behavior is it meant to reflect? A KPI with no
   purpose gets gamed or ignored. Prefer metrics that map to real value, not vanity.
2. **Write the exact formula.** Numerator, denominator, and every inclusion/exclusion. "Active users"
   is meaningless until you specify the action and window. Ambiguity here is the root of most bad reporting.
3. **Specify the source and window.** Which system of record, over what time period (daily/weekly/monthly,
   rolling vs. calendar). Same metric, different window = different number and endless confusion.
4. **Set target and threshold.** What value is good, and at what level does it warrant action? A KPI
   without a target can't drive behavior.
5. **Guard against gaming.** Consider how the KPI could be hit while missing its intent (e.g. cutting
   quality to raise speed). Pair it with a guardrail metric where needed. `write_memory` (type `learning`).
6. **Document as the single source.** `update_company_playbook` with the definitions; all dashboards and
   reports (`metrics-dashboard-setup`, `reporting-automation`) must use them verbatim.

## Decision framework — one definition, everywhere
A KPI is only useful if computed identically across every report and period. When in doubt, over-specify
the definition; the cost of ambiguity is contradictory numbers and lost trust.

## Definition of done
- Purpose stated; exact formula with inclusions/exclusions; source and window specified.
- Target/threshold set; gaming risk addressed with guardrails; documented as the single source.

## Common failure modes
- **Vague formulas.** "Active users" without a precise action/window means everyone reports differently.
- **Window drift.** Rolling vs. calendar windows quietly change the number.
- **Gameable KPIs.** Metrics hit by sacrificing the thing they were meant to protect.
