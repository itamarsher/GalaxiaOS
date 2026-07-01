---
name: unit-economics-analysis
title: Unit Economics Analysis
description: Compute per-customer economics (CAC, LTV, payback, margin) to know if growth is profitable.
roles: finance, growth, ceo
---
# Unit Economics Analysis

Growth only creates value if each customer is worth more than it costs to acquire and serve.
This playbook computes the core unit economics so the fleet grows profitably, not expensively.

## Workflow
1. **Define the unit.** Usually a customer or account. Be consistent so the numbers compare.
2. **Compute CAC.** Total sales + marketing spend (`read_financials`, ad spend from
   `run_ad_campaign` history) ÷ customers acquired in the period. Include all acquisition cost, not
   just media.
3. **Compute contribution margin.** Revenue per customer minus the cost to serve them (COGS,
   support, infra). A customer isn't profitable at revenue — only at margin.
4. **Compute LTV.** Margin per period × expected lifetime (derived from churn — `churn-reduction-playbook`
   / `cohort-analysis`). Use real retention, not hoped-for retention.
5. **Derive the health ratios:** LTV/CAC (aim > 3), CAC payback period (months to recoup CAC —
   shorter protects runway), and margin. `record_metric` each.
6. **Segment and act.** Compute by channel/segment — some acquire profitably, some at a loss.
   `write_memory` (type `learning`) which segments to scale and which to cut; feed `pricing-experiment`
   and `paid-ads-campaign-launch` scale decisions.

## Decision framework — scale gate
Only pour money into acquisition when LTV/CAC and payback are healthy for that specific channel/
segment. Scaling negative unit economics accelerates the path to zero runway.

## Definition of done
- CAC (fully loaded), contribution margin, and LTV (from real churn) computed.
- LTV/CAC, payback, and margin recorded; segmented; scale/cut guidance produced.

## Common failure modes
- **Revenue mistaken for profit.** Only margin counts; serving costs are real.
- **Fantasy retention.** LTV built on hoped-for churn overstates everything.
- **Blended-only view.** Averages hide unprofitable channels that should be cut.
