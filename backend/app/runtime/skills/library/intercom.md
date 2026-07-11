---
name: intercom
title: Intercom
description: Handle support conversations, deploy the Fin AI agent, or send proactive in-app messages in Intercom when running customer support and messaging.
roles: product, growth
---
# Intercom

Intercom is the fleet's customer messaging and support desk — a shared inbox, the Fin AI agent,
workflows, help center, and proactive messages. This skill is the ABOS-adapted path to using it well:
**connect it as a tool first, never assume it's wired**, then let AI answer first while humans own the
edge cases. Support outcomes and contacts sync to the ABOS CRM (`crm_find_contacts`, `crm_log_activity`).

## Connect before you message
1. **Find the tool.** `discover_tools` with query `intercom`; it exposes as `mcp__intercom__*` once it's connected (by you or the founder). Load what you need with `use_tool` (read a conversation, reply, trigger a
   workflow).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Intercom in
   Settings (access token or MCP server). Never invent a reply, ticket, or resolution — a fabricated
   support answer can mislead a real customer.
3. **Least privilege + egress.** Customer conversation data through Intercom is data egress; if
   sensitive data is involved, `check_compliance` / `list_data_policies` first.

## Automate the front line, escalate the edge
4. **Let Fin answer first — on good content.** Fin is only as good as your help-center content, so keep
   articles current and specific; give Fin explicit guidance for tricky topics. Fin on the front line
   cuts inbox volume and resolves instantly.
5. **Workflows route, escalate, and enforce SLAs.** Build workflows to triage by topic, apply SLAs so
   high-priority tickets get fast response, and set clean escalation to a human (or `dispatch_task` the
   product agent) when Fin can't resolve.
6. **Proactive messages are gated external comms.** Outbound in-app/email messages (onboarding nudges,
   outage notices, re-engagement) are indexed into the external-comms log and may need sign-off —
   respect the approval gate and `check_compliance`; trigger on behavior, not blast-all.
7. **Feed the help center from real tickets.** Recurring questions become articles, which makes Fin
   better next time — the loop compounds.

## File the deliverable and record it
8. **Sync outcomes.** `crm_log_activity` notable conversations against the contact; `save_file`
   (category `artifact`) any published help-center content or workflow config as the durable record.
9. **Record + hand off.** `write_memory` (type `result`) recurring issues and fixes; `record_metric`
   for resolution rate / Fin deflection / SLA attainment; `report_result` or `open_issue` on product bugs surfaced.

## Definition of done
- Intercom confirmed connected (or escalated, never faked); customer-data egress checked.
- Fin answering first on current content; workflows enforce SLAs and clean human escalation.
- Proactive messages passed the comms gate; outcomes logged to CRM; help center updated from real tickets.

## Common failure modes
- **Phantom reply.** Claiming a customer was answered when Intercom was never connected — escalate instead.
- **Fin on stale content.** Deploying the AI agent over thin/outdated articles, so it answers wrong.
- **Blast proactive messages.** Sending untriggered mass messages without the comms gate or compliance check.
