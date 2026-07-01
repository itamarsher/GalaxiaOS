---
name: quarterly-strategy-review
title: Quarterly Strategy Review
description: Step back to assess progress against strategy, kill what isn't working, and reset priorities.
roles: ceo, governance
---
# Quarterly Strategy Review

The daily loop optimizes execution; the quarter is when you check you're executing the right
things. This playbook is the periodic step-back that resets strategy on evidence.

## Workflow
1. **Grade last period honestly.** Score OKR attainment (`read_metrics`, `company-okr-planning`).
   State what was hit, missed, and why — no spin. A padded review corrupts the next quarter's decisions.
2. **Assess the strategy, not just execution.** Are the bets still right given what you learned
   (`win-loss-analysis`, `industry-trend-scan`, `voice-of-customer-synthesis`)? Sometimes you executed
   well on the wrong thing.
3. **Check the fundamentals.** Runway (`runway-and-burn-analysis`), unit economics
   (`unit-economics-analysis`), and traction. These constrain what strategy is even possible.
4. **Kill and double down.** Explicitly stop initiatives that aren't working — freeing budget/attention
   is the point. Double down where evidence is strong. Indecision is the expensive default.
5. **Reset priorities.** Set next-quarter OKRs (`company-okr-planning`); `set_agent_directive` and
   `set_agent_budget` to reallocate the fleet toward them.
6. **Communicate.** `create_report` (kind `status_report`) for the founder; `write_memory` (type
   `result`) the strategic decisions and their rationale so future reviews have continuity.

## Decision framework — sunk cost is not a reason
Judge each initiative on expected future return, not on how much has been invested. The quarter's
value comes from the courage to stop things, not just to start them.

## Definition of done
- OKRs graded honestly; strategy (not just execution) reassessed against evidence and fundamentals.
- Explicit kill/double-down decisions; next-quarter priorities set and resourced; communicated.

## Common failure modes
- **Reviewing execution, not strategy.** Doing the wrong thing efficiently.
- **Sunk-cost persistence.** Keeping failing bets alive because of past investment.
- **No kills.** A review that only adds priorities isn't a review; it's a pile-up.
