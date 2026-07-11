---
name: hubspot
title: HubSpot
description: Manage contacts, lifecycle stages, lead scoring, marketing workflows, or pipeline reporting in HubSpot when the company's CRM and marketing hub live in HubSpot.
roles: growth, ceo
---
# HubSpot

HubSpot is the fleet's combined CRM and marketing hub — contacts, deals, lifecycle stages, automated
workflows, and the reports leadership steers by. This skill is the ABOS-adapted path to using it well:
**connect it as a tool first, never assume it's wired**, then keep the data clean enough that automation
and reporting can be trusted.

## Connect before you touch records
1. **Find the tool.** `discover_tools` with query `hubspot`; it exposes as `mcp__hubspot__*` once the
   founder has connected it. Load what you need with `use_tool` (search contacts, run a workflow, pull a report).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect HubSpot in
   Settings (MCP server or private-app token). Never invent a contact, deal, or pipeline number — a
   phantom record corrupts every downstream report.
3. **Least privilege + egress.** HubSpot holds customer/prospect PII; syncing or exporting is data egress.
   `check_compliance` / `list_data_policies` before flowing PII out. Prefer ABOS `crm_*` tools where they exist.

## Keep the model clean and the automation honest
4. **Lifecycle stages are one-way and defined.** Use the standard ladder (Subscriber → Lead → MQL → SQL →
   Opportunity → Customer). Drive MQL by an **active list** (real-time, self-correcting), not a brittle
   workflow trigger, and never let a stage move backward.
5. **Score fit + engagement, review on a schedule.** Split the model between fit (firmographics) and
   engagement (behavior); document the point logic in the score description; revisit monthly/quarterly.
   HubSpot's AI scoring surfaces patterns manual rules miss — use it to prioritize, not to auto-close.
6. **Workflows: one job each, clearly named.** Small, single-purpose workflows (assignment, stage update,
   nurture) beat one mega-flow — easier to audit and to unwind when they misfire.
7. **Report on real data, never a guess.** Pull deal/pipeline/attribution numbers via `mcp__hubspot__*`
   or `read_metrics`; if the founder asks for a figure you can't source, escalate rather than estimate.

## File the deliverable and record it
8. **File exports and reports.** `save_file` (category `artifact`, or `financial` for revenue/pipeline
   reporting) with the HubSpot link — the file store is the durable, shareable source.
9. **Record + gate outbound.** Marketing emails/sequences are external comms: respect the approval gate.
   `record_metric` real outcomes, `write_memory` (type `result`), `report_result`.

## Definition of done
- HubSpot confirmed connected (or escalated, never faked); PII egress checked.
- Lifecycle via active lists, scoring documented, workflows single-purpose; reports from real data.
- Deliverables filed with the link, outbound gated, outcome recorded.

## Common failure modes
- **Phantom pipeline.** Reporting deals or MQLs that don't exist in HubSpot — read real data or escalate.
- **Mega-workflow.** One tangled automation nobody can audit; splits into single-purpose flows.
- **Stale scoring.** A model set once and never revisited, so priorities drift from reality.
