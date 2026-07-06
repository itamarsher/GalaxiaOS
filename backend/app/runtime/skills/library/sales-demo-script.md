---
name: sales-demo-script
title: Sales Demo Script
description: Build a tailored demo that maps each feature shown to a pain the buyer already stated.
roles: growth, ceo, product
---
# Sales Demo Script

A demo persuades when every click answers a problem the buyer already named. This
playbook turns discovery notes into a tight, tailored script — not a feature tour.

## Prerequisite
Do not demo before discovery. If there's no `write_memory` of the buyer's quantified
pain, run `sales-discovery-call-prep` first.

## Workflow
1. **Pull the pains.** Read the discovery memory and `crm_contact_timeline`. List the
   2–4 problems the buyer stated, in their words.
2. **Map features to pains.** For each pain, pick the single most relevant capability to
   show. Anything that doesn't map to a stated pain is cut. Confirm the capability exists;
   if a needed feature isn't built, say so honestly and `dispatch_task` to product rather
   than demoing vaporware.
3. **Script the arc** per pain: *"You told me X costs you Y → here's how this removes it →
   here's the proof."* End each with a check-in question ("does that match what you need?").
4. **Prepare assets.** If you need a walkthrough visual, `generate_image`; for a short
   recorded flow, `generate_video`. Keep them specific to the buyer's use case.
5. **Define the ask.** Decide the single next step the demo drives toward (trial, proposal,
   multi-threaded intro). `write_memory` it as the demo's success criterion.
6. **Log and follow up.** After the demo, `crm_log_activity` with reactions per pain and
   `update_deal` to the next stage; `schedule_followup` with the agreed next step.

## Decision framework — what to cut
If showing a feature requires explaining a concept the buyer didn't ask about, cut it.
Depth on their pain beats breadth across your product.

## Definition of done
- Every demoed feature traces to a stated, quantified pain.
- One clear next-step ask defined and logged.
- Deal stage and reactions recorded after the call.

## Common failure modes
- **The feature tour.** Showing everything signals you didn't listen.
- **Demoing the roadmap as if it's shipped.** Route unbuilt needs to product; don't fake them.
- **No next step.** A great demo with no ask stalls the deal.
