---
name: feature-prioritization
title: Feature Prioritization
description: Rank the backlog by value, effort, and confidence so the fleet builds what matters most next.
roles: product, ceo
---
# Feature Prioritization

A backlog without prioritization is a wishlist. This playbook ranks candidates by expected
value against cost and confidence so the next thing built is the highest-leverage thing.

## Workflow
1. **Gather candidates from evidence.** Pull from `list_feature_requests`, discovery
   (`product-discovery-interviews`), and churn/expansion signals. Each candidate should trace to
   a real problem, not a whim.
2. **Score each on RICE-style factors:**
   - *Reach* — how many users/accounts it affects.
   - *Impact* — how much it moves the objective it serves.
   - *Confidence* — how sure we are (discount hopeful guesses).
   - *Effort* — realistic build cost (ask platform via `dispatch_task` if unsure).
   Score = (Reach × Impact × Confidence) / Effort.
3. **Sanity-check against strategy.** A high score that doesn't serve the current objective is a
   distraction. `mission-alignment-check` if in doubt.
4. **Sequence, don't just rank.** Account for dependencies and quick wins that unblock others.
   `submit_plan` with the ordered top items and their rationale.
5. **Record and communicate.** `write_memory` (type `result`) the ranking and its drivers;
   `update_company_playbook` or `create_report` so the fleet shares one priority list.
6. **Revisit on new evidence**, not on every loud request — re-score when reach/impact/confidence
   genuinely change.

## Decision framework — the confidence discount
Multiply optimistic value by honest confidence. A huge-impact bet you're unsure of can rank
below a modest, certain win. Beware effort estimates that ignore testing and edge cases.

## Definition of done
- Candidates traced to real problems; scored on reach/impact/confidence/effort.
- Sequenced with dependencies; shared as one prioritized list.

## Common failure modes
- **HiPPO-driven order.** The loudest stakeholder isn't the scoring model.
- **Ignoring confidence.** Optimism inflates everything equally; discount it.
- **Underestimating effort.** "Just a small change" hides testing, edge cases, and rework.
