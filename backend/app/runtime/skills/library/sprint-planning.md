---
name: sprint-planning
title: Sprint Planning
description: Plan a focused, capacity-honest sprint with a clear goal the fleet can actually deliver.
roles: product, platform
---
# Sprint Planning

A sprint without a goal is a to-do list that slips. This playbook plans a focused increment the
fleet can realistically deliver, tied to the roadmap.

## Workflow
1. **Set one sprint goal.** A single sentence describing the outcome this sprint delivers. It
   comes from the roadmap Now column (`product-roadmap-planning`). Multiple unrelated goals = no goal.
2. **Pull ready work only.** Take top-priority items that are actually ready — problem clear,
   PRD/acceptance criteria defined (`prd-writing`), dependencies unblocked. Unready work stalls mid-sprint.
3. **Estimate against real capacity.** Check `list_team` and honest availability. Plan to ~80% of
   capacity, leaving room for the unexpected. Overcommitting guarantees a miss.
4. **Define done per item.** Acceptance criteria and the metric/behavior that proves it works.
   Ambiguous "done" causes rework and disputes.
5. **Assign and commit.** `dispatch_tasks` to owning roles with the sprint goal attached; `submit_plan`
   the sprint scope so it's visible.
6. **Track and protect the goal.** Mid-sprint, defend against scope creep (`request_decision` for
   real additions); at close, review delivered vs. goal and `write_memory` (type `learning`) the
   estimate accuracy to improve the next plan.

## Decision framework — commit vs. stretch
Commit only to what you'd bet on delivering at ~80% capacity. Stretch items are explicitly
optional. A sprint that always over-commits trains everyone to distrust the plan.

## Definition of done
- One sprint goal from the roadmap; only ready work pulled; planned to ~80% capacity.
- Per-item acceptance criteria; scope protected; estimate accuracy captured at close.

## Common failure modes
- **No goal.** A pile of unrelated tickets with nothing to protect.
- **Over-committing.** 100%+ plans miss and demoralize.
- **Unready work.** Items with fuzzy requirements stall the whole sprint.
