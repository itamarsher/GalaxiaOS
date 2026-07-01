---
name: marketing-creative-production
title: Marketing Creative Production
description: Produce on-brand marketing creative tied to a specific campaign goal and audience.
roles: design, growth
---
# Marketing Creative Production

Creative that isn't tied to a goal is art, not marketing. This playbook produces campaign assets that
serve a specific objective and audience while staying on-brand.

## Workflow
1. **Start from the brief.** What campaign, what goal (awareness, clicks, conversion), what audience,
   what channel/format? Get it from the requesting growth skill (`paid-ads-campaign-launch`,
   `social-media-campaign`). No brief = no production.
2. **Anchor to the message and brand.** Pull the single message from `positioning-and-messaging` and the
   look from `brand-identity-kit`. One clear message per asset — cramming several dilutes all of them.
3. **Design for the channel.** Format, dimensions, and attention pattern differ by placement (feed vs.
   search vs. email). A great asset in the wrong format underperforms.
4. **Produce variants to test.** `generate_image` / `generate_video` a small set varying one element
   (hook, visual, CTA) so growth can A/B them (`ab-test-design`). Don't hand over a single untested asset.
5. **Check claims and compliance.** Every claim in creative must be true and, if regulated, compliant
   (`check_compliance`). Creative passes the external-comms governance gate — no overclaiming.
6. **Deliver and learn.** `save_file` / hand to `dispatch_task`; after the campaign, `write_memory`
   (type `learning`) which creative direction won, to inform the next batch.

## Decision framework — one message, many tests
Each asset carries one message; a campaign carries several asset variants to learn from. Clarity per
asset plus variety across the set beats one busy do-everything creative.

## Definition of done
- Produced from a goal/audience brief; on-message and on-brand; formatted per channel.
- Testable variants delivered; claims true and compliant; winning direction recorded.

## Common failure modes
- **Goal-less creative.** Pretty assets that serve no measurable objective.
- **Message cramming.** Multiple messages per asset that dilute impact.
- **Overclaiming.** Creative makes claims the product can't back — a governance/legal risk.
