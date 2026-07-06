---
name: prd-writing
title: PRD Writing
description: Write a crisp product requirements doc that says what to build, for whom, and how success is judged.
roles: product
---
# PRD Writing

A PRD turns a prioritized idea into something buildable and testable. This playbook writes one
that's crisp enough to build from and honest about what's out of scope.

## Workflow
1. **Start from the problem.** Restate the user problem and evidence (link discovery memories).
   If you can't state the problem crisply, it's not ready for a PRD — go back to discovery.
2. **Define the user and the job.** Who is this for and what job are they trying to do
   (`jobs-to-be-done-analysis`)? Name the primary user; secondary users are noted, not centered.
3. **Specify the solution at the right altitude.** Describe required behavior and the key flows —
   not pixel-level design (that's for design) nor implementation (that's for platform). Include
   the must-haves; explicitly list non-goals to prevent scope creep.
4. **Define success upfront.** State the metric(s) that will show the feature worked, and the
   target. A PRD with no success metric can't be evaluated. `write_memory` (type `experiment`).
5. **Cover the edges.** Error states, empty states, permissions, and data/privacy implications
   (`list_data_policies`; `check_compliance` if regulated).
6. **Draft and circulate.** `draft_document` the PRD; `dispatch_task` to design and platform for
   feasibility input; revise. Store it (`save_file`) and link it from the roadmap.

## Decision framework — detail vs. flexibility
Specify the *what* and *why* precisely; leave the *how* to the builders. Over-specifying
implementation wastes effort and demoralizes; under-specifying success makes it un-gradeable.

## Definition of done
- Problem, user, and job stated with evidence; solution at behavior altitude; non-goals listed.
- Success metric and target defined; edge cases and data/privacy covered.

## Common failure modes
- **Solution in search of a problem.** No clear problem = premature PRD.
- **No success metric.** You can't tell if it worked.
- **Scope creep.** Missing non-goals let the feature balloon.
