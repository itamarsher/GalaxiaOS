---
name: attio
title: Attio
description: Model the CRM, build objects/attributes, wire enrichment or workflows, or pull a report in Attio when the customer graph lives (or should live) in Attio.
roles: growth
---
# Attio

Attio is the fleet's data-model-first CRM — objects, attributes, and relationships you shape yourself,
with enrichment and workflows layered on top. This skill is the ABOS-adapted path to using it well:
**connect it as a tool first, never assume it's wired**, then model the data before you automate it.
ABOS's own `crm_*` tools stay the system of record; Attio is the graph you sync into and report from.

## Connect before you model
1. **Find the tool.** `discover_tools` with query `attio`; it exposes as `mcp__attio__*` once the founder
   has connected it. Load what you need with `use_tool` (read records, upsert, run a workflow).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Attio in
   Settings (MCP server or API key). Never invent a record link or claim a company exists — a phantom
   contact is worse than none, and it corrupts every downstream report.
3. **Least privilege + egress.** Pushing people/company data to Attio is third-party egress; if anything
   sensitive flows out, `check_compliance` / `list_data_policies` first.

## Model the data, then automate
4. **Standard objects before custom.** Use built-in People, Companies, and Deals where they fit — they
   carry native enrichment and email/calendar sync. Reach for custom objects only for genuinely new
   entities, and give attributes a stable type (don't overload one text field for five meanings).
5. **Let enrichment and sync do the research.** Email/calendar sync auto-creates People and Companies and
   records who spoke to whom; enrichment fills firmographics and hierarchy. Trust current data over stale
   notes — mirror ABOS's `crm_find_contacts`/`crm_save_contact` state in, don't retype.
6. **Lists are views, not sources.** Segment and pipeline in Lists; keep the truth on the object. Build
   workflows on field updates, stage changes, or object creation to route leads and enforce hygiene, and
   use AI attributes to summarize/classify rather than leaving fields blank.

## File the deliverable and record it
7. **Export reports and file.** Export the report or view and `save_file` (category `artifact`) with the
   Attio link in the description; the file store is the durable, shareable source, not agent memory.
8. **Record + hand off.** Mirror the outcome with `crm_save_deal`/`update_deal`, `record_metric` the
   pipeline number, `write_memory` (type `result`), then `report_result` or `dispatch_task` follow-up.

## Definition of done
- Attio confirmed connected (or escalated, never faked); sensitive-data egress checked.
- Standard objects used where possible; attributes typed; enrichment/sync trusted over manual entry.
- Report exported and `save_file`d, outcome mirrored to ABOS CRM and recorded.

## Common failure modes
- **Phantom records.** Claiming a contact or deal exists when Attio was never connected — escalate instead.
- **Custom-object sprawl.** New objects and free-text attributes for things standard fields already model.
- **Automating on a dirty model.** Workflows fired against unclean data multiply the mess instead of the value.
