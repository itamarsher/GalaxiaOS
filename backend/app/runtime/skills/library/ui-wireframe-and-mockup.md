---
name: ui-wireframe-and-mockup
title: UI Wireframe & Mockup
description: Turn a product requirement into clear wireframes and mockups that communicate the intended experience.
roles: design, product
---
# UI Wireframe & Mockup

Wireframes and mockups turn a PRD into something buildable and testable before code is written. This
playbook produces them to communicate the experience clearly and catch problems cheaply.

## Workflow
1. **Start from the PRD and job.** Pull the requirement, user, and success metric (`prd-writing`,
   `jobs-to-be-done-analysis`). Design serves the job; decoration without a job is wasted.
2. **Wireframe the flow first.** Low-fidelity layout of the key screens and the path between them —
   structure and hierarchy before visuals. Solving the flow cheaply prevents expensive rework later.
3. **Design for the primary task.** Make the one action the user needs obvious; everything else is
   secondary. Clarity and reducing friction beat visual flourish (`landing-page-optimization` mindset).
4. **Apply the design system.** Use existing components and patterns (`design-system-setup`) so the work
   is consistent and buildable. Inventing new patterns per screen creates inconsistency and dev cost.
5. **Mock up the key states.** Don't just show the happy path — include empty, loading, error, and edge
   states. These are where real usage lives and where builders get stuck without guidance.
6. **Validate and hand off.** Walk it against the user's job; `dispatch_task` to platform with the mockups
   and state notes. `save_file`; `write_memory` (type `result`) the intended experience.

## Decision framework — flow before pixels
Solve structure and flow at low fidelity before polishing visuals. A beautiful screen with a broken
flow fails; a plain screen with a clear flow works. Fidelity should increase only as confidence does.

## Definition of done
- Grounded in the PRD/job; flow wireframed before visuals; primary task made obvious.
- Design-system components used; key states (empty/loading/error) mocked; validated and handed off.

## Common failure modes
- **Pixel-polishing a broken flow.** High fidelity on an unsolved structure.
- **Happy-path only.** Missing empty/error states leaves builders and users stranded.
- **Reinventing patterns.** Bespoke components per screen break consistency and slow dev.
