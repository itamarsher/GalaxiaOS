---
name: data-quality-audit
title: Data Quality Audit
description: Systematically check that the data driving decisions is accurate, complete, and consistent.
roles: data, auditor
---
# Data Quality Audit

Decisions are only as good as the data behind them. This playbook checks that data is accurate,
complete, and consistent — because a confident decision on bad data is worse than admitted uncertainty.

## Workflow
1. **Scope by decision-criticality.** Audit the data that drives real decisions (metrics, financials)
   first. Not all data warrants equal scrutiny; prioritize what would cause harm if wrong.
2. **Check accuracy against the source.** Reconcile reported numbers to the system of record
   (`read_metrics`, `read_financials`, `record_transaction` history). A number that doesn't tie out is a red flag.
3. **Check completeness.** Are there gaps, missing periods, or dropped records? Silent missing data skews
   averages and hides trends. Quantify what's missing rather than ignoring it.
4. **Check consistency.** Does the same metric agree across reports (`kpi-definition`)? Contradictory
   numbers for the "same" metric usually mean a definition or pipeline problem.
5. **Check for anomalies.** Look for impossible values, sudden unexplained jumps, and duplicates. Each is
   a symptom of a collection or processing bug. `flag_legal_risk` if financial data integrity is affected.
6. **Report and fix root cause.** `write_memory` (type `result`) issues found and severity; `dispatch_task`
   to fix the pipeline, not just the number; `create_report` on data health. Re-audit after fixes.

## Decision framework — trust must be earned
Treat data as suspect until reconciled, especially before a big decision. Fix the root cause (the
pipeline/definition), not just the visible symptom, or the same bad number returns next period.

## Definition of done
- Decision-critical data prioritized; accuracy reconciled to source; completeness and consistency checked.
- Anomalies identified; root causes fixed (not just symptoms); data health reported; re-audited.

## Common failure modes
- **Trusting unreconciled numbers.** Confident decisions on unverified data.
- **Ignoring missing data.** Silent gaps skew every aggregate.
- **Symptom fixes.** Patching a number without fixing the pipeline that produced it.
