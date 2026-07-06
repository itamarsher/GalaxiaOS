---
name: social-graphics-batch
title: Social Graphics Batch
description: Produce a consistent batch of social graphics efficiently, on-brand and sized per platform.
roles: design, growth
---
# Social Graphics Batch

Social needs a steady stream of on-brand visuals. This playbook produces them in efficient, consistent
batches — so the feed looks coherent and the fleet isn't designing one-offs under deadline.

## Workflow
1. **Work from the campaign plan.** Pull the posts and messages from `social-media-campaign` /
   `content-marketing-calendar`. Batch-produce against a plan, not ad hoc per post.
2. **Template for consistency.** Establish a few reusable layouts from `brand-identity-kit` (quote card,
   announcement, stat, carousel). Templates make a batch coherent and fast; freestyling each makes it messy.
3. **Produce the batch.** `generate_image` for each post's visual, filling the templates with the specific
   message. Keep one clear message per graphic — feeds reward clarity, punish clutter.
4. **Size per platform.** Different placements need different dimensions/crops. Export the right sizes so
   nothing is awkwardly cropped at post time.
5. **Check brand and claims.** Consistent colors/type/logo usage; every claim true (assets pass the
   external-comms gate). `check_compliance` if any post makes regulated claims.
6. **Deliver scheduled.** Hand off with `schedule_social_post` so the batch flows out on cadence;
   `write_memory` (type `learning`) which formats drove engagement to refine the next batch.

## Decision framework — batch and template, don't freestyle
Consistency and throughput come from reusable templates and batching. Producing each graphic from
scratch is slower and yields an incoherent feed. Systematize the recurring, customize the message.

## Definition of done
- Produced against the campaign plan using reusable on-brand templates; one message per graphic.
- Correctly sized per platform; claims true/compliant; delivered scheduled; format learnings recorded.

## Common failure modes
- **Freestyling every post.** Slow, and the feed looks incoherent.
- **Wrong dimensions.** Awkward crops signal carelessness.
- **Cluttered graphics.** Multiple messages per image kill readability in-feed.
