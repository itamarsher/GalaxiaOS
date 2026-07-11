---
name: linear
title: Linear
description: Track engineering work — file bugs, plan a cycle, groom the backlog, or run the product roadmap when the team works out of Linear.
roles: product, platform
---
# Linear

Linear is where the fleet's engineering work lives — issues, cycles, and projects that product and platform execute against. This skill is the ABOS-adapted path to using it well: **connect it as a tool first, never assume it's wired**, then work with Linear's grain instead of against it.

## Connect before you plan
1. **Find the tool.** `discover_tools` with query `linear`; Linear exposes as `mcp__linear__*` once the founder has connected it. Load what you need with `use_tool` (create an issue, move a cycle, read a project).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Linear in Settings (MCP server or API key), scoped to the team you touch. If the capability can't exist yet, `request_capability`. Never invent an issue ID or claim a ticket exists — a phantom ticket is worse than none.
3. **Least privilege + egress.** Writing to Linear sends work data to a third party; if an issue would carry anything sensitive, `check_compliance` / `list_data_policies` first.

## Work with Linear's grain
4. **Route new work through Triage, not the backlog.** Land bugs and requests in Triage, then categorize and assign before they enter the backlog — this keeps the backlog from becoming a dumping ground. ABOS bugs from `report_bug` / `open_issue` belong here.
5. **Match the hierarchy to scope.** An **issue** is one unit of work; a **cycle** is the near-term sprint (1–2 weeks); a **project** is a longer initiative spanning cycles. The roadmap updates live from project progress — don't hand-maintain a separate one.
6. **Keep statuses and labels tight.** Use 5–7 workflow statuses; don't replicate a status as a label or add a status that only exists for reporting — that belongs in a comment or project update. Labels are for cross-cutting tags, kept small.
7. **Let git close the loop.** Put the issue identifier in the branch/PR name; Linear moves the issue to In Review on PR open and Done on merge. Don't transition by hand what the integration transitions for you.

## File the deliverable and record it
8. **Link and record.** `write_memory` (type `result`) the issue/project URL and what shipped; `record_metric` for cycle throughput or bugs closed when relevant.
9. **Hand off.** `dispatch_task` the platform agent to implement, or `report_result` with the Linear link.

## Definition of done
- Linear confirmed connected (or escalated, never faked); sensitive-data egress checked.
- Work landed at the right level (issue/cycle/project), routed through Triage, statuses and labels kept tight.
- Issue/project link recorded, outcome handed off.

## Common failure modes
- **Phantom ticket.** Claiming an issue exists when Linear was never connected — escalate instead.
- **Status/label sprawl.** Bespoke statuses and duplicate labels that break Linear's velocity model and reporting.
- **Manual git bookkeeping.** Transitioning issues by hand instead of naming branches to auto-link and auto-close.
