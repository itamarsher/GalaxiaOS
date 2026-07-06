---
name: jobs-to-be-done-analysis
title: Jobs-To-Be-Done Analysis
description: Frame what users are really trying to accomplish so the product solves the job, not the feature request.
roles: product, research
---
# Jobs-To-Be-Done Analysis

Users don't want features; they hire products to get a job done. This playbook uncovers the
real job — functional, emotional, and social — so you build what actually gets "hired."

## Workflow
1. **Gather the raw material.** Interviews (`product-discovery-interviews`), support and sales
   notes, and `list_feature_requests`. Look for what users were trying to accomplish, not what
   they asked for.
2. **Write jobs as outcomes.** Format: "When [situation], I want to [motivation], so I can
   [expected outcome]." Keep it solution-free — "so I can trust my numbers," not "so I can export CSV."
3. **Separate the job layers:** functional (the task), emotional (how they want to feel), social
   (how they want to be seen). Missing the emotional/social layer is why some technically-correct
   features flop.
4. **Find the hiring and firing moments.** What triggers someone to seek a solution, and what makes
   them abandon one? These reveal the highest-value moments to serve.
5. **Map jobs to opportunities.** For each important, underserved job, note how well current
   solutions (including ours) do it. Gaps are roadmap candidates → `feature-prioritization`.
6. **Record and share.** `write_memory` (type `learning`) the core jobs; `update_company_playbook`
   so product, positioning, and design all target the same jobs.

## Decision framework — job vs. solution
If a statement mentions a feature or UI, it's a solution, not a job — dig one level deeper. Build
for the enduring job; solutions change, jobs are stable.

## Definition of done
- Jobs written as solution-free outcome statements across functional/emotional/social layers.
- Hiring/firing moments identified; underserved jobs mapped to opportunities and shared.

## Common failure modes
- **Solutions disguised as jobs.** "Wants CSV export" is a solution; find the job beneath it.
- **Only the functional layer.** Emotional/social drivers explain adoption and churn.
- **Analysis with no output.** Jobs must feed prioritization and positioning to matter.
