---
name: product-feedback-loop
title: Product Feedback Loop
description: Build a durable loop that routes user feedback to decisions and closes back to the user.
roles: product, data
---
# Product Feedback Loop

Feedback is only valuable if it changes decisions and the user sees it land. This playbook
builds the standing loop: collect → synthesize → decide → close back.

## Workflow
1. **Consolidate inputs.** Feedback arrives via support, sales (`crm_contact_timeline`), NPS
   (`nps-and-testimonial-collection`), community, and `list_feature_requests`. Centralize it so
   no channel is a silo.
2. **Synthesize into themes**, not tickets. `feature-request-triage` to cluster into problems with
   demand and value weighting. `write_memory` (type `learning`) the recurring themes.
3. **Route to the right decision.** Bugs → `report_bug`; validated problems → `feature-prioritization`;
   messaging gaps → growth; pricing signals → finance. Feedback with no owner dies.
4. **Decide and record.** For top themes, make an explicit call (build / not now / won't do) with
   a reason. `submit_plan` or `write_memory` (type `result`).
5. **Close the loop with users.** Tell people what happened to their input — shipped, planned, or
   declined-with-reason (`send_notification` / `send_email`). This is what keeps feedback flowing.
6. **Measure the loop.** `record_metric` for feedback volume, time-to-response, and % of themes
   actioned. A loop that collects but never closes silently dies.

## Decision framework — theme vs. ticket
Decide on themes (problems many share), not individual tickets. One good decision on a theme
resolves dozens of tickets.

## Definition of done
- Inputs centralized; synthesized into weighted themes; each top theme has an owner and a decision.
- Users informed of outcomes; loop health measured.

## Common failure modes
- **Channel silos.** Feedback split across tools hides real demand.
- **Ticket-by-ticket firefighting.** Reacting to individuals instead of themes.
- **Never closing back.** Unheard users stop giving feedback.
