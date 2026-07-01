---
name: founder-decision-brief
title: Founder Decision Brief
description: Package a decision the founder must make into a crisp, honest brief they can act on quickly.
roles: ceo, governance
---
# Founder Decision Brief

The founder acts as a board member, not an operator — their time is scarce. This playbook packages a
decision that genuinely needs them into a brief they can act on in minutes, with full context.

## Workflow
1. **Confirm it needs the founder.** Is this within the fleet's authority, or does it truly require the
   founder (irreversible, mission-level, large spend, external commitment, value trade-off)? Don't
   escalate what the fleet should own; don't sit on what it shouldn't.
2. **State the decision in one line.** The specific choice to be made, up top. The founder should grasp
   what's being asked before any context.
3. **Give just enough context.** The situation, why it matters now, and the relevant real numbers
   (`read_metrics`, `read_financials`). Enough to decide, not a data dump — respect their time.
4. **Present options with trade-offs.** 2–3 real options, each with its upside, downside, cost, and
   reversibility. Include your recommendation and why — a brief without a recommendation offloads the
   analysis back onto the founder.
5. **State the stakes and the clock.** What happens if they decide each way, and by when a decision is
   needed. Make the cost of delay explicit if there is one.
6. **Route and track.** `request_decision` with the brief; `schedule_followup` if time-sensitive; on
   response, `write_memory` (type `result`) the decision and `dispatch_tasks` the follow-through.

## Decision framework — decision-ready, not raw
A good brief lets the founder decide from the brief alone. If they'd need to go dig for context or do
the analysis themselves, it isn't ready — sharpen it first.

## Definition of done
- Escalation genuinely warranted; decision stated in one line; just-enough context with real numbers.
- 2–3 options with trade-offs and a clear recommendation; stakes/timing explicit; decision tracked to action.

## Common failure modes
- **Over-escalation.** Bringing the founder decisions the fleet should own erodes their leverage.
- **Data dumps.** Raw context without a recommendation makes the founder do the work.
- **No recommendation or clock.** Leaves the decision unframed and easy to defer.
