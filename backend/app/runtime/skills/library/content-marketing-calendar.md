---
name: content-marketing-calendar
title: Content Marketing Calendar
description: Plan a themed content calendar tied to buyer questions and business objectives, not random topics.
roles: growth, ceo
---
# Content Marketing Calendar

Sporadic content compounds to nothing. This playbook builds a themed calendar where every
piece serves a buyer question and a business objective, with a cadence the fleet can sustain.

## Workflow
1. **Anchor to objectives.** State which objective the content serves (demand, SEO, trust).
   Content with no objective is a hobby — skip it.
2. **Mine real questions.** `web_search` for what the ICP actually asks; pull themes from
   sales calls (`crm_contact_timeline`) and support/feature requests (`list_feature_requests`).
3. **Build pillars, not one-offs.** Choose 3–5 topic pillars; each calendar slot is a piece
   that reinforces a pillar and links to the others (topic-cluster model — pairs with `seo-keyword-strategy`).
4. **Set a sustainable cadence.** Pick a frequency the fleet can hold for a quarter (e.g. 1
   deep piece/week beats 5 then silence). Map slots to dates.
5. **Assign and schedule.** For each slot, `dispatch_task` to production (see `blog-post-production`)
   and `schedule_social_post` for distribution. Store the calendar via `save_file` or `update_company_playbook`.
6. **Review monthly.** `read_metrics` for traffic/leads per pillar; double down on the pillar
   that converts, cut the one that doesn't. `write_memory` (type `learning`) the finding.

## Decision framework — depth vs. volume
When capacity is tight, choose fewer, deeper pieces. One authoritative asset out-earns five
thin ones for SEO and trust.

## Definition of done
- 3–5 pillars set, each slot mapped to a pillar, objective, and date.
- Cadence is sustainable for a full quarter; calendar stored where the fleet can find it.

## Common failure modes
- **Topic roulette.** Unconnected posts don't build authority or rankings.
- **Cadence you can't hold.** A dead blog signals a dead company.
- **No measurement loop.** Without per-pillar metrics you can't prune.
