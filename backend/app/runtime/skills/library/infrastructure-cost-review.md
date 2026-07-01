---
name: infrastructure-cost-review
title: Infrastructure Cost Review
description: Review infrastructure and tooling spend to cut waste without risking reliability, protecting runway.
roles: platform, finance
---
# Infrastructure Cost Review

Infra and tooling costs creep quietly and eat runway. This playbook reviews them to cut genuine waste —
without the false economy of undermining reliability.

## Workflow
1. **Inventory the spend.** `read_financials` for infra/tooling costs by line item. You can't optimize
   what you can't see; surface every recurring charge, including forgotten subscriptions.
2. **Map cost to value.** For each item, what does it enable and is it load-bearing? Distinguish essential
   reliability spend from convenience and from pure waste (unused seats, idle resources, duplicate tools).
3. **Find the waste.** Idle/over-provisioned resources, unused licenses, and redundant tools are usually the
   biggest quick wins. `write_memory` (type `learning`) the candidates with their monthly cost.
4. **Weigh cuts against risk.** Cutting reliability/monitoring/backup spend to save money is often a false
   economy — one incident costs more than a year of the savings. Cut waste aggressively; touch resilience carefully.
5. **Right-size, don't just cut.** Often the win is matching capacity to real usage (`read_metrics`), not
   removing capability. `dispatch_task` the changes; verify nothing breaks (`deploy-and-release-ops` caution).
6. **Recommend and track.** `create_report` (kind `financial_report`) with the savings and any risk
   trade-offs; `request_decision` on anything touching reliability; `record_metric` the run-rate reduction.

## Decision framework — cut waste, protect resilience
Attack idle and redundant spend without hesitation; treat reliability, security, and backup spend as
near-sacred. The goal is efficiency that extends runway, not fragility that shortens the company's life.

## Definition of done
- All recurring infra/tooling spend inventoried and mapped to value; waste identified with costs.
- Cuts weighed against reliability risk; right-sized to real usage; savings recommended, decided, and tracked.

## Common failure modes
- **False economy.** Cutting monitoring/backup to save pennies, then paying for it in an incident.
- **Invisible creep.** Forgotten subscriptions and idle resources never surfaced.
- **Cut, not right-size.** Removing capability when matching capacity to usage would do.
