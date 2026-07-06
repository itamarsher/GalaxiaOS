---
name: user-story-mapping
title: User Story Mapping
description: Map the user's journey into a shared story backbone so scope decisions are visible and coherent.
roles: product
---
# User Story Mapping

A story map turns a flat backlog into the user's journey, making scope trade-offs visible.
This playbook builds one so the team cuts scope by slice, not at random.

## Workflow
1. **Frame the user and goal.** Which user, achieving what end-to-end outcome? A map without a
   protagonist is just a task list.
2. **Lay the backbone.** Left-to-right, the sequence of activities the user does to reach the
   goal (the big steps). This is the narrative spine.
3. **Add detail downward.** Under each backbone step, list the specific tasks/stories, most
   essential at top. Pull candidates from `list_feature_requests` and PRDs.
4. **Slice releases horizontally.** Draw a line across the top row: the thinnest slice that lets
   the user complete the whole journey (a walking skeleton). Lower rows are later releases.
5. **Decide scope by slice.** Cutting a horizontal slice keeps a coherent end-to-end experience;
   cutting a vertical column breaks the journey. Prefer thinner slices over missing steps.
6. **Feed planning.** Turn the top slice into the next `sprint-planning` input; `save_file` /
   `submit_plan` the map so the fleet shares one picture.

## Decision framework — horizontal over vertical cuts
When you must cut, cut depth (do each step more simply), not breadth (drop a step). A journey
missing a step doesn't work; a journey done simply does.

## Definition of done
- Backbone captures the end-to-end journey; tasks prioritized under each step.
- A thin, coherent first slice defined and handed to planning.

## Common failure modes
- **Flat backlog masquerading as a map.** No backbone = no scope insight.
- **Cutting columns.** Dropping a journey step breaks the whole flow.
- **Mapping without a user.** The story needs a protagonist and a goal.
