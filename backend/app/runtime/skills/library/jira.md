---
name: jira
title: Jira
description: Manage software delivery in Jira — create epics and stories, plan a sprint, build a board, or query issues with JQL when the team runs on Jira.
roles: product, platform
---
# Jira

Jira is where the fleet's delivery is planned and tracked when a team runs on Atlassian — epics, stories, sprints, and boards. This skill is the ABOS-adapted path to using it well: **connect it as a tool first, never assume it's wired**, then resist the urge to over-configure it.

## Connect before you plan
1. **Find the tool.** `discover_tools` with query `jira`; Jira exposes as `mcp__jira__*` once it's connected (by you or the founder). Load what you need with `use_tool` (create an issue, transition it, run a JQL search).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Jira in Settings (MCP server or API token), scoped to the project you touch. If the capability can't exist yet, `request_capability`. Never invent an issue key or claim a ticket exists — a phantom ticket is worse than none.
3. **Least privilege + egress.** Writing to Jira sends work data to a third party; if an issue would carry anything sensitive, `check_compliance` / `list_data_policies` first.

## Structure without over-configuring
4. **Use the standard hierarchy.** Epic → Story → Task/Sub-task. Anything the team estimates in weeks is an epic to be broken down; hours-to-days work is a single story. Give each epic a measurable goal in its description and link its children.
5. **Keep workflows and fields lean.** Start from Jira's defaults and add complexity only when it clearly earns its keep. Excess statuses, custom fields, and issue types slow teams, hurt performance, and confuse new members — review and prune them.
6. **Plan sprints deliberately.** Fixed 1–4 week iterations with real start/end dates accounting for holidays, and a sprint goal displayed prominently on the board. Don't carry an ever-growing sprint.
7. **Write efficient JQL.** Filter on indexed fields (`project`, `issuetype`, `status`, `assignee`); keep `OR` in the outer clause and `AND` inside brackets; avoid `!=`/`NOT`/negation. Save and reuse good filters instead of re-deriving them.

## File the deliverable and record it
8. **Link and record.** `write_memory` (type `result`) the issue/epic URL and what shipped; `record_metric` for sprint throughput or bugs closed when relevant.
9. **Hand off.** `dispatch_task` the platform agent to implement, or `report_result` with the Jira link.

## Definition of done
- Jira confirmed connected (or escalated, never faked); sensitive-data egress checked.
- Work sits at the right level with a real epic goal; workflow/fields kept minimal; sprint has dates and a goal.
- Issue/epic link recorded, outcome handed off.

## Common failure modes
- **Phantom ticket.** Claiming an issue exists when Jira was never connected — escalate instead.
- **Over-configuration.** Bespoke statuses, fields, and issue types that no one maintains and that drag performance.
- **Sprawling JQL.** Negations and un-indexed fields that run slow and get copy-pasted instead of saved.
