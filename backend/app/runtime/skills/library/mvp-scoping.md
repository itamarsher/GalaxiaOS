---
name: mvp-scoping
title: MVP Scoping
description: Cut a product idea down to the smallest version that tests the core hypothesis honestly.
roles: product, ceo
---
# MVP Scoping

An MVP exists to learn, cheaply and fast. This playbook cuts an idea to the smallest thing
that produces a real signal — without shipping something so thin it teaches nothing.

## Workflow
1. **Name the hypothesis and the risk.** What's the riskiest assumption — that people want it,
   that we can build it, or that they'll pay? The MVP targets the riskiest one. `write_memory`
   (type `experiment`).
2. **Define the learning signal.** What observable outcome would confirm or kill the hypothesis
   (sign-ups, usage, willingness to pay)? Decide before building.
3. **Cut to the core.** List everything the full vision includes, then remove anything not needed
   to test the hypothesis. Polish, edge cases, and scale come later. Ruthlessly.
4. **Choose the cheapest valid test.** Sometimes that's a landing page or a concierge/manual
   version, not code. If a no-code test answers the question, build that (`dispatch_task`).
5. **Set a time box.** MVPs sprawl without a deadline. Commit a date; `submit_plan` with scope
   and date.
6. **Ship, measure, decide.** Launch to a small real audience; `record_metric` the learning
   signal; `write_memory` (type `result`) whether the hypothesis held and what's next.

## Decision framework — thin vs. broken
Cut scope, not quality of the core experience. An MVP should do one thing well, not ten things
badly. "Minimum" trims breadth; "viable" protects the one thing that must work.

## Definition of done
- Riskiest hypothesis and learning signal defined; scope cut to only what tests it.
- Cheapest valid test chosen; time-boxed; signal measured and a decision recorded.

## Common failure modes
- **Building the vision, calling it an MVP.** If it isn't cut hard, it isn't minimum.
- **Broken core.** "Viable" means the one essential thing works.
- **No kill criterion.** An MVP you can't fail teaches nothing.
