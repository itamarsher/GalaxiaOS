---
name: zendesk
title: Zendesk
description: Run customer support in Zendesk — handle tickets, build a macro, set SLAs, wire triggers/automations, publish help-center content, or track CSAT.
roles: product
---
# Zendesk

Zendesk is where the fleet does customer support — tickets, the macros and rules that move them, and the help center customers self-serve from. This skill is the ABOS-adapted path to using it well: **connect it as a tool first, never assume it's wired**, then automate deliberately instead of drowning the queue in conflicting rules.

## Connect before you reply
1. **Find the tool.** `discover_tools` with query `zendesk`; Zendesk exposes as `mcp__zendesk__*` once the founder has connected it. Load what you need with `use_tool` (read/update a ticket, apply a macro, run a view).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Zendesk in Settings (API token, least privilege). If the capability can't exist yet, `request_capability`. Never invent a ticket ID or claim a customer was answered — a phantom reply is worse than none.
3. **External comms are gated.** Every reply and published help article goes out to a customer and is indexed into the external-comms log; respect the approval gate and don't route around it. Screen sensitive data with `check_compliance` first.

## Automate deliberately
4. **Know the three tools apart.** **Macros** are agent-applied templates; **triggers** are event-based rules that fire on create/update; **automations** are time-based rules. Reach for the one that matches, don't force one to do another's job.
5. **Build macros that do the whole action.** A good macro sets the comment mode, inserts a personalized reply (dynamic placeholders), updates status, and adds a unique tracking tag — a macro that only flips status wastes the reply.
6. **Start with a handful of rules, then grow.** Begin with ~5–10 core triggers for common scenarios; too many conflict and become impossible to debug. Route by keyword/property (or AI intent/sentiment) to the right group, and add SLA-risk triggers that escalate before a breach.
7. **Close the loop with CSAT.** Auto-solve then survey after a set solved period; trigger a reopen-and-tag on negative feedback so bad experiences get a second touch instead of vanishing.

## File the deliverable and record it
8. **Record and measure.** `write_memory` (type `result` or `learning`) recurring themes and rule changes; `record_metric` for CSAT, first-response, and SLA compliance.
9. **Hand off.** `dispatch_task` a product/engineering fix for a systemic issue behind the tickets, or `report_result`.

## Definition of done
- Zendesk confirmed connected (or escalated, never faked); replies respect the external-comms gate; sensitive data screened.
- Right rule type used; macros do the full action; trigger set kept small; SLAs and CSAT wired.
- Outcomes recorded, metrics captured, systemic fixes handed off.

## Common failure modes
- **Phantom reply.** Claiming a customer was answered when Zendesk was never connected — escalate instead.
- **Rule sprawl.** Dozens of overlapping triggers that conflict and bounce tickets between queues.
- **Half a macro.** A macro that flips status without sending the standard, personalized message.
