---
name: hiring-a-new-agent-role
title: Hiring a New Agent Role
description: Decide when the fleet needs a new role, define it well, and add it within budget and governance.
roles: ceo, governance
---
# Hiring a New Agent Role

Adding an agent adds capability and cost. This playbook decides when a new role is truly needed,
defines it sharply, and adds it within budget and oversight — the ABOS analog of hiring.

## Workflow
1. **Confirm the need is real and structural.** Is there sustained work no existing role owns, gating
   an objective? A temporary spike is a `dispatch_task`, not a new hire. `list_team` to see current coverage.
2. **Define the role precisely.** Its single clear responsibility, the objective it serves, its scope,
   and how its success is measured. A fuzzy role produces fuzzy work and overlaps others.
3. **Justify the budget.** Every agent consumes budget (LLM + actions). Confirm the runway supports it
   (`runway-and-burn-analysis`) and size its allocation. `request_budget` / `request_decision` for the
   founder's sign-off on a material addition.
4. **Respect governance.** Ensure oversight roles (governance, auditor, data) still exist and aren't
   diluted — the fleet must keep its guardrails. Don't add operators at the expense of oversight.
5. **Onboard with a directive.** `hire_agent` with a clear `set_agent_directive` and `set_agent_budget`.
   Give it its first concrete objective and success metric so it starts grounded.
6. **Review fit.** After a period, assess whether the role earns its cost (reputation/ROI signals);
   `write_memory` (type `learning`). Be willing to `pause_agent` a role that isn't paying off.

## Decision framework — hire vs. redistribute
Add a role only when the work is durable, unowned, and gating a goal — and the budget supports it.
When in doubt, redistribute to existing roles first; a lean fleet extends runway.

## Definition of done
- Structural, unowned need confirmed; role defined with one responsibility and a success metric.
- Budget justified within runway and approved; governance preserved; onboarded with a directive; fit reviewed.

## Common failure modes
- **Hiring for a spike.** Temporary load is a task, not a permanent role.
- **Fuzzy roles.** Undefined responsibility creates overlap and diffuse accountability.
- **Diluting oversight.** Adding operators while starving governance breaks the guardrails.
