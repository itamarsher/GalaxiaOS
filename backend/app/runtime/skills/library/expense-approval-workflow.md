---
name: expense-approval-workflow
title: Expense Approval Workflow
description: Run a proportionate approval process that controls spend without strangling the fleet.
roles: finance, governance
---
# Expense Approval Workflow

Every dollar the fleet spends passes through the budget. This playbook approves expenses in
proportion to their size and risk — controlling waste without becoming a bottleneck.

## Workflow
1. **Check it against budget first.** `read_financials` for remaining budget in the relevant
   category. An expense with no budget headroom is a `request_budget`/escalation, not an approval.
2. **Tier by size and reversibility.** Small, reversible spend inside budget → approve and log.
   Large, irreversible, or out-of-budget spend → `request_decision` from the CEO/founder. Match
   scrutiny to stakes.
3. **Test necessity and ROI.** Does this spend serve an objective, and is it the cheapest way to
   get the outcome? Reject nice-to-haves that don't move a goal.
4. **Watch for irreversibility.** Real external charges (domains, ads, services) commit real money
   through the CostMeter — confirm budget is reserved before the irreversible call, never after.
5. **Record and approve.** On approval, `record_transaction` and `crm_log_activity`/`log_ops_event`
   as appropriate. On rejection, state the reason so the requester can adjust.
6. **Audit periodically.** `write_memory` (type `learning`) recurring spend patterns; feed
   `financial-spend-audit` to catch drift and unnecessary recurring costs.

## Decision framework — proportionate control
Scrutiny should scale with size × irreversibility. Rubber-stamping large spend invites waste;
gating tiny reversible spend wastes more in friction than it saves. Tier it.

## Definition of done
- Budget headroom checked; spend tiered by size/reversibility; necessity and ROI tested.
- Irreversible spend reserved before commit; decisions recorded with reasons.

## Common failure modes
- **Approving beyond budget.** The cap is hard; over-budget spend needs escalation.
- **One-size scrutiny.** Gating everything equally is either too loose or too slow.
- **Committing before reserving.** Irreversible charges must clear budget first.
