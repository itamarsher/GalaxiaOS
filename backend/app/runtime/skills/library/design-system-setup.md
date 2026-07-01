---
name: design-system-setup
title: Design System Setup
description: Establish reusable components and tokens so product and marketing look consistent and ship faster.
roles: design, platform, product
---
# Design System Setup

A design system is the shared vocabulary that makes everything consistent and faster to build. This
playbook establishes a lean one — enough structure to enforce consistency without becoming overhead.

## Workflow
1. **Derive from the brand.** Tokens (color, type, spacing) come from `brand-identity-kit`. The system
   is how the brand becomes consistent, buildable code and design — not a separate aesthetic.
2. **Start with tokens, then components.** Define the primitives (colors, typography scale, spacing,
   radii) first; build components (buttons, inputs, cards) from them. Tokens make global change trivial.
3. **Build the components you actually use.** Create the handful of components the product and site need
   now, not a speculative library of everything. Grow it on demand (`ui-wireframe-and-mockup` reveals needs).
4. **Document usage.** For each component: what it's for, its variants, and when NOT to use it. An
   undocumented system gets used inconsistently and defeats its purpose.
5. **Make it the single source.** `save_file` / `update_company_playbook`; `dispatch_task` platform to
   implement in code. All UI work (`ui-wireframe-and-mockup`, landing pages) must draw from it.
6. **Maintain it.** `write_memory` (type `learning`) new patterns as they stabilize; retire or merge
   redundant components. A system that isn't maintained fragments back into chaos.

## Decision framework — lean and used over complete and ignored
Build the components in real use and document them well, rather than a vast library nobody adopts.
A small, well-adopted system beats a comprehensive, ignored one.

## Definition of done
- Tokens derived from the brand; components built from tokens for real current needs and documented.
- Established as the single source in the playbook and implemented; maintained as patterns evolve.

## Common failure modes
- **Speculative over-building.** A huge library of unused components.
- **Undocumented components.** Get used inconsistently, defeating the point.
- **No maintenance.** Systems rot into inconsistency without upkeep.
