---
name: freshdesk
title: Freshdesk
description: Handle support tickets, set SLA policies, automate dispatch/routing, manage canned responses, run CSAT, or maintain the knowledge base in Freshdesk.
roles: product
---
# Freshdesk

Freshdesk is the fleet's support desk — inbound tickets, SLAs, automation, and the self-service knowledge
base. This skill is the ABOS-adapted path to using it well: **connect it as a tool first, never assume it's
wired**, then automate the desk so response is fast and consistent without inventing anything. Ticket
outcomes that touch a customer relationship belong back in ABOS's `crm_*` record.

## Connect before you triage
1. **Find the tool.** `discover_tools` with query `freshdesk`; it exposes as `mcp__freshdesk__*` once it's connected (by you or the founder). Load what you need with `use_tool` (read/update tickets, set rules, KB articles).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Freshdesk in
   Settings (MCP server or API key). Never invent a ticket, resolution, or CSAT score — a phantom ticket
   hides a real customer who's still waiting.
3. **Replies are external comms.** Agent responses go to customers and are indexed; if a reply carries
   sensitive data or a commitment, `check_compliance` and respect the approval gate — don't route around it.

## Automate the desk
4. **Three automation types, right trigger.** Use Dispatch'r at creation to categorize/prioritize/route,
   Observer on change to react, and Supervisor on a schedule to catch aging tickets and escalate breaches.
5. **SLA policies set the clock.** Define response/resolution targets, with separate policies for customer
   tier, product, or shift; Supervisor should escalate before a breach, not report it after.
6. **Canned responses and scenarios for consistency.** Maintain canned replies for common issues and bundle
   multi-step actions into scenarios (insert reply, set priority, assign, tag) so a routine ticket is one click.
7. **Deflect with the knowledge base.** Keep KB articles current so customers self-serve; every recurring
   ticket theme is a signal to write or update an article, cutting volume at the source.

## Close the loop and record it
8. **Measure and file.** Track CSAT sliced by agent/group/channel and `record_metric` the trend; `save_file`
   (category `artifact`) any resolution summary or KB export with the Freshdesk link.
9. **Record + hand off.** `crm_log_activity` the interaction against the customer, `write_memory` (type
   `learning`) recurring root causes, then `report_result` or `dispatch_task` product for the underlying fix.

## Definition of done
- Freshdesk confirmed connected (or escalated, never faked); customer-facing replies respect the comms gate.
- Dispatch/Observer/Supervisor and SLA policies configured; canned responses and KB kept current.
- CSAT measured, interaction logged to ABOS CRM, recurring causes recorded and handed off.

## Common failure modes
- **Phantom ticket.** Claiming a ticket or resolution exists when Freshdesk was never connected — escalate.
- **Silent SLA breach.** No Supervisor rule, so aging tickets blow their SLA before anyone notices.
- **Stale knowledge base.** Outdated articles that deflect nothing, so agents re-answer the same question forever.
