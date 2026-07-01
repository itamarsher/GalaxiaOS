---
name: mission-alignment-check
title: Mission Alignment Check
description: Test a major decision or initiative against the company's mission and constraints before committing.
roles: ceo, governance
---
# Mission Alignment Check

The fleet moves fast; drift from the mission is a real risk. This playbook is a quick, honest gate
that tests whether a major decision actually serves the mission and its constraints.

## Workflow
1. **Restate the mission and constraints.** Pull the exact mission and hard constraints
   (`get_company_playbook`, `docs/MISSION.md` context). Check against what the company committed to, not
   a vibe.
2. **State the decision plainly.** What are we about to do, and what does it cost (budget, focus,
   reputation)? Vague framing hides misalignment.
3. **Test alignment directly.** Does this advance the mission, or just look like progress? Does it
   honor the constraints (e.g. the open-core, BYOK, user-ownership commitments) or quietly violate them?
   A profitable move that betrays the mission is a strategic error.
4. **Check for value conflicts.** Would this decision damage user trust, compromise the open commitment,
   or trade long-term mission for short-term gain? `flag_legal_risk` / `request_decision` if it touches a
   core value.
5. **Decide with eyes open.** If aligned, proceed and note why. If misaligned, either reshape it to fit
   or reject it. If it's a genuine mission trade-off, escalate to the founder — the fleet shouldn't
   silently redefine the mission.
6. **Record.** `write_memory` (type `learning`) the alignment judgment and its reasoning, so the fleet's
   direction stays coherent over time.

## Decision framework — mission over local optimum
When a decision helps a metric but conflicts with the mission or constraints, the mission wins or the
founder decides. The fleet's job is to pursue the mission efficiently, not to drift toward whatever
scores well this week.

## Definition of done
- Mission and constraints restated from the real source; decision and its cost stated plainly.
- Alignment and value-conflict tested honestly; aligned/reshaped/rejected/escalated with recorded reasoning.

## Common failure modes
- **Vibe-checking, not testing.** Alignment asserted without checking the actual mission text.
- **Silent mission drift.** Redefining the mission to fit a tempting decision.
- **Metric over mission.** Optimizing a local number at the mission's expense.
