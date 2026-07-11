---
name: salesforce
title: Salesforce
description: Manage leads, opportunities, pipeline, or reporting in Salesforce when the customer record of truth lives (or should live) in Salesforce CRM.
roles: growth, ceo
---
# Salesforce

Salesforce is the fleet's external system of record for accounts, pipeline, and forecasting. This
skill is the ABOS-adapted path to using it well: **connect it as a tool first, never assume it's
wired**, then keep the object model and pipeline clean enough to trust the forecast. ABOS mirrors
the same records internally (`crm_save_contact`, `crm_save_deal`, `crm_log_activity`) — keep the two
in sync, don't let them drift.

## Connect before you touch records
1. **Find the tool.** `discover_tools` with query `salesforce`; it exposes as `mcp__salesforce__*`
   once the founder has connected it. Load what you need with `use_tool` (query a report, upsert an
   opportunity).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Salesforce
   in Settings (MCP server or connected app). Never invent an opportunity ID or claim a record exists —
   a phantom pipeline is worse than none.
3. **Least privilege + egress.** Writing customer PII to Salesforce is data egress; if sensitive data
   flows out, `check_compliance` / `list_data_policies` first.

## Keep the model and pipeline trustworthy
4. **Leads vs. contacts vs. opportunities.** A Lead is an unqualified individual; convert to
   Account + Contact + Opportunity only when qualified. Don't create Opportunities off raw inbound —
   that inflates the forecast. Mirror qualified deals with `crm_save_deal`.
5. **Actionable stages with exit criteria.** Each opportunity stage needs a defined probability and
   explicit exit criteria; avoid vague labels like "In Progress." Align the whole fleet on one
   definition so forecast rolls up cleanly.
6. **Enforce hygiene at entry.** Validation rules, picklists, and dependent fields prevent dirty data
   at the source; dedupe on import. Dirty data is the top cause of broken forecasts.
7. **Report on the process, not vanity.** Build reports/dashboards on stage conversion, aging, and
   pipeline coverage — surface the stage where deals leak.

## File the deliverable and record it
8. **Export and file.** `save_file` the report/dashboard export (category `artifact`) with the
   Salesforce link in the description.
9. **Record + hand off.** `write_memory` (type `result`) the pipeline state; `record_metric` for
   pipeline value and conversion; `report_result` or `schedule_followup` on stalled deals.

## Definition of done
- Salesforce confirmed connected (or escalated, never faked); PII egress checked.
- Qualified deals only as Opportunities; stages have exit criteria; hygiene enforced by validation rules.
- Report filed with link; pipeline metrics recorded; ABOS CRM mirror kept in sync.

## Common failure modes
- **Phantom pipeline.** Reporting deals when Salesforce was never connected — escalate instead.
- **Leads as opportunities.** Unqualified inbound inflating the forecast until it's meaningless.
- **Stages without exit criteria.** "In Progress" everywhere, so probability and forecast are guesses.
