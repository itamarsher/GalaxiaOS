---
name: asana
title: Asana
description: Stand up a project, structure tasks and custom fields, automate with rules, or roll work into portfolios and goals in Asana — the fleet's work tracker.
roles: product, ceo
---
# Asana

Asana is where the fleet plans and tracks execution — projects, tasks, custom fields, and the portfolios
and goals that roll them into strategy. This skill is the ABOS-adapted path to using it well: **connect it
as a tool first, never assume it's wired**, then structure work so it stays one source of truth instead of
another silo. Keep execution here; don't spin up a parallel tracker for the same work.

## Connect before you plan
1. **Find the tool.** `discover_tools` with query `asana`; it exposes as `mcp__asana__*` once it's connected (by you or the founder). Load what you need with `use_tool` (create projects/tasks, set fields, add rules).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Asana in
   Settings (MCP server or API key). Never invent a task link or claim a project exists — a phantom plan
   misleads everyone reading status.
3. **One tracker, not five.** Before creating a project, check whether the work already lives somewhere; new
   projects for existing work are how tool sprawl starts. `list_company_files` / read the playbook first.

## Structure so it scales
4. **Match structure to project type.** Pick the view for how the work runs — Board for process/Kanban,
   List or Timeline for deadline-driven. Structure follows the pattern, not habit.
5. **Global fields over one-off fields.** Use organization-wide custom fields (status, priority, effort) so
   work is comparable across projects and rolls into portfolios; reserve local fields for the truly project-specific.
6. **Rules and bundles for consistency.** Automate routing, assignment, and status changes with rules; apply
   bundles (reusable field/rule/template sets) so every project of a type is set up the same way — less
   manual upkeep, fewer divergent processes.
7. **Portfolios and goals for the roll-up.** Group related projects into portfolios for at-a-glance on-track/
   at-risk, and link to goals so the CEO view ties execution to outcomes, not task counts.

## File the deliverable and record it
8. **Export the plan and file.** Export the project plan or portfolio status and `save_file` (category
   `artifact`) with the Asana link — the durable, shareable source, not agent memory.
9. **Record + hand off.** `record_metric` progress against the goal, `write_memory` (type `result`) the plan
   link, then `report_result` or `dispatch_task` the owning agents.

## Definition of done
- Asana confirmed connected (or escalated, never faked); no duplicate tracker created for existing work.
- View matched to project type; global fields, rules/bundles applied; work rolled into portfolios/goals.
- Plan exported and `save_file`d, progress recorded and handed off.

## Common failure modes
- **Tool sprawl.** A fresh project for work that already lives elsewhere, fragmenting the single source of truth.
- **Phantom plan.** Claiming a project or task exists when Asana was never connected — escalate instead.
- **Field free-for-all.** One-off local fields everywhere, so nothing rolls up into portfolios or goals.
