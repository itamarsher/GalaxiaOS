---
name: bug-triage-and-escalation
title: Bug Triage & Escalation
description: Triage incoming bugs by severity and impact, and escalate the ones that can't wait.
roles: platform, product
---
# Bug Triage & Escalation

Not every bug is equal, and treating them equally means the critical one waits behind cosmetic ones. This
playbook triages by real impact and escalates what genuinely can't wait.

## Workflow
1. **Reproduce and confirm.** Before triaging, confirm the bug is real and reproducible (`read_repo_file`,
   `report_bug` context). An unreproducible report needs more info, not a fix; a non-bug wastes the queue.
2. **Assess severity × reach.** Severity (data loss/security > broken core > degraded > cosmetic) times how
   many users hit it. A cosmetic bug everyone sees and a data-loss bug one user hits are both higher priority
   than they first look — score both dimensions.
3. **Escalate the criticals immediately.** Security, data-integrity, or widespread-outage bugs don't wait
   in a queue — treat as an incident (`crisis-and-incident-response`), `flag_legal_risk` if data/security,
   and escalate now.
4. **Prioritize the rest.** Order by severity × reach against effort. Feed non-urgent bugs into the normal
   queue (`open_issue`, `feature-prioritization`); a bug is a negative feature — it competes for the same capacity.
5. **Route with context.** `dispatch_task` to the owning role with repro steps, severity, and impact.
   Handing off a bug without repro steps just bounces it back.
6. **Track to closure and learn.** Confirm fixes land and verify them; `write_memory` (type `learning`)
   recurring bug patterns that suggest a systemic fix (`incident-postmortem` for the worst).

## Decision framework — impact, not recency or volume
Prioritize by severity × reach, not by who complained loudest or most recently. A quiet data-corruption
bug outranks a noisy cosmetic one. Criticals bypass the queue entirely.

## Definition of done
- Bugs reproduced/confirmed; scored on severity × reach; criticals escalated as incidents immediately.
- Remainder prioritized against effort and routed with repro context; tracked to verified closure.

## Common failure modes
- **FIFO triage.** First-in-first-out ignores that some bugs are far more damaging.
- **Queuing a critical.** Letting a security/data bug wait behind cosmetic ones.
- **Repro-less handoffs.** Routing bugs without steps just ping-pongs them.
