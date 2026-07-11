---
name: notion
title: Notion
description: Build or maintain the company knowledge base in Notion — a wiki, a tracked database with relations, a doc template, or shared workspace structure.
roles: product, ceo
---
# Notion

Notion is the fleet's shared brain — wikis, docs, and databases that the whole company reads and writes. This skill is the ABOS-adapted path to using it well: **connect it as a tool first, never assume it's wired**, then structure so the workspace stays navigable as it grows.

## Connect before you build
1. **Find the tool.** `discover_tools` with query `notion`; Notion exposes as `mcp__notion__*` once it's connected (by you or the founder). Load what you need with `use_tool` (create a page, query a database, update properties).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Notion in Settings (integration token), shared only to the pages the integration needs. If the capability can't exist yet, `request_capability`. Never invent a Notion link or claim a page exists — a phantom doc is worse than none.
3. **Least privilege + egress.** Writing to Notion sends company knowledge to a third party; if content is sensitive, `check_compliance` / `list_data_policies` first, and remember Notion permissions are set at the database level — access is uniform across its data sources.

## Structure so it scales
4. **Model data as databases, not loose pages.** Anything with repeating structure — tasks, customers, decisions — is a database with typed properties, not scattered pages. Use **relations** to link databases (a task to its project) and **rollups** to surface linked values instead of duplicating them.
5. **Give the workspace one navigable spine.** A clear home/wiki page linking to each area beats deep nesting; start simple and grow deliberately rather than pre-building a maze.
6. **Templates for anything recurring.** Database templates standardize new entries (meeting notes, specs, tickets) so structure is consistent without manual reformatting.
7. **Set permissions intentionally.** Scope Can-edit vs Can-view per audience, and lock template databases so shared structure isn't accidentally broken. Prefer native Slack/Calendar/GitHub connections over manual copy-paste to keep data in sync.

## File the deliverable and record it
8. **Link and record.** `write_memory` (type `result`) the Notion URL and what it holds; `save_file` an export if a durable artifact copy is needed (category `artifact`).
9. **Hand off.** `dispatch_task` whoever must act on the page, or `report_result` with the link.

## Definition of done
- Notion confirmed connected (or escalated, never faked); sensitive-content egress and permissions checked.
- Structured data as databases with relations/rollups; one navigable spine; recurring content templated.
- Page/database link recorded and handed off.

## Common failure modes
- **Phantom doc.** Claiming a page exists when Notion was never connected — escalate instead.
- **Loose pages over databases.** Repeating info scattered as pages, so it can't be filtered, rolled up, or kept in sync.
- **Permission sprawl.** Over-sharing a database (uniform across its sources) or leaving templates editable and breakable.
