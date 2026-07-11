---
name: airtable
title: Airtable
description: Design or populate a base — tables, linked records, views, automations, or interfaces — when structured operational data should live in Airtable.
roles: data, platform
---
# Airtable

Airtable is the fleet's flexible relational store — bases of linked tables that ops, CRM, and content
pipelines build on. It is a real database, not a spreadsheet: model it like one. The ABOS-adapted principle:
**connect it as a tool first, never assume it's wired**, then design a schema that stays sane as it grows.

## Connect before you build
1. **Find the tool.** `discover_tools` with query `airtable`; it exposes as `mcp__airtable__*` once it's connected (by you or the founder). Load what you need with `use_tool` (list bases, read/create records).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Airtable in
   Settings (MCP server or PAT). Never invent a record ID or claim a base exists — a phantom base is worse
   than none.
3. **Least privilege + egress.** Reading/writing a base moves company data to a third party; `check_compliance`
   / `list_data_policies` if sensitive fields are involved.

## Model it like a relational database
4. **One table per entity; link, don't duplicate.** Each table is a distinct list (Companies, Contacts,
   Deals). Relate them with **linked-record fields** — never copy the same columns into a second table.
   Links are bidirectional, so both sides stay in sync automatically.
5. **Views, not new tables, for slices.** Filtered/grouped/hidden-field views give each collaborator or stage
   its own lens on the *same* records — spinning up a table per person or status fragments the data.
6. **Automate in-base; respect the API limits.** Use Airtable automations for record-triggered steps and
   Interfaces for human-facing dashboards. Against the API, obey **5 requests/second per base** (429 →
   wait 30s) and **batch up to 10 records per request** instead of one-at-a-time writes.

## File the deliverable and record it
7. **Document + record.** `write_memory` (type `result`) the base/table structure and its purpose; `save_file`
   a schema note or export (category `artifact`) so the design survives without opening Airtable.

## Definition of done
- Airtable confirmed connected (or escalated, never faked); egress checked.
- One table per entity, related via linked records; slices are views; writes batched under the rate limit.
- Structure documented and outcome recorded.

## Common failure modes
- **Duplicated tables.** Copying similar fields into parallel tables instead of linking — the data drifts
  out of sync.
- **Table-per-slice sprawl.** A new table per collaborator or status where a filtered view would do.
- **Rate-limit 429s.** One-record-at-a-time writes with no batching, tripping the 5 req/s cap.
