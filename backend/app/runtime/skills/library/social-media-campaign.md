---
name: social-media-campaign
title: Social Media Campaign
description: Run a focused, themed social campaign with a clear goal and a sustainable posting rhythm.
roles: growth, design
---
# Social Media Campaign

This playbook runs a time-boxed social campaign around one theme and goal — awareness,
launch, or engagement — rather than posting into the void.

## Workflow
1. **Define goal + channel fit.** Pick one primary goal and the 1–2 channels where the ICP
   actually is. Don't spread thin across every platform.
2. **Set the theme and hook.** One campaign narrative; every post is a facet of it. State the
   success metric (reach, clicks, signups) and `write_memory` (type `experiment`) the target.
3. **Batch the assets.** `dispatch_task` to design or `generate_image` / `generate_video` for
   a coherent set. Keep visual identity consistent (pull from `get_company_playbook`).
4. **Schedule the rhythm.** `schedule_social_post` across the campaign window at a cadence you
   can sustain; sequence posts so they build (tease → reveal → proof → CTA).
5. **Engage, don't just broadcast.** Plan to respond to replies — social is a conversation.
   Route inbound interest to `log_lead`.
6. **Measure.** `record_metric` per post and for the campaign; `write_memory` (type `learning`)
   the hook and format that outperformed.

## Governance note
Social posts are external messages — they pass the fleet's external-comms approval gate.
Don't post anything that would embarrass the company or make unverified claims.

## Definition of done
- One goal, right channels, one theme, sustainable cadence.
- Assets on-brand; engagement plan defined; per-post metrics recorded.

## Common failure modes
- **Everywhere at once.** Thin presence on five platforms beats no one; pick where the ICP is.
- **Broadcast-only.** Ignoring replies wastes the reach you earned.
- **Off-brand or overclaiming assets.** They pass a governance gate — keep them honest.
