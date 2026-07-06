---
name: nps-and-testimonial-collection
title: NPS & Testimonial Collection
description: Measure satisfaction, route detractors to fixes, and turn promoters into proof and referrals.
roles: growth, product
---
# NPS & Testimonial Collection

Satisfaction data is only useful if it drives action: fix detractor pain, amplify promoter
love. This playbook closes that loop and produces social proof honestly.

## Workflow
1. **Survey at the right moment** — after a value milestone, not randomly. Keep it to the NPS
   question plus one open "why." Send via `send_email`; `crm_log_activity`.
2. **Score and segment.** Promoters (9–10), passives (7–8), detractors (0–6). `record_metric`
   the NPS; `write_memory` (type `learning`) the themes in the "why" answers.
3. **Close the loop on detractors.** Route their specific pain to the owning role
   (`dispatch_task`) — a fix or reply turns a detractor around and prevents churn. Never ignore
   a detractor to protect the score.
4. **Activate promoters.** Ask promoters for a testimonial or referral (`referral-program-launch`).
   Use their exact words — with permission — as proof. `flag_legal_risk` / `request_user_action`
   if consent for public use is unclear.
5. **Never fabricate proof.** Testimonials must be real, attributable, and consented. Inventing
   or embellishing quotes is a hard line — it's fraud and a legal risk.
6. **Feed product.** Aggregate themes into `list_feature_requests` / `write_memory` so the score
   drives roadmap, not just morale.

## Decision framework — score vs. truth
Never optimize the NPS number by suppressing detractor sends or cherry-picking. A true score
that drives fixes beats a flattering one that hides problems.

## Definition of done
- Timed survey; NPS recorded; detractor pain routed to owners.
- Promoter proof collected with consent; themes fed to product. No fabricated quotes.

## Common failure modes
- **Vanity-gaming the score.** Suppressing detractors hides the problems you need to fix.
- **Fabricated testimonials.** Fraud and legal risk — every quote must be real and consented.
- **Collecting, not acting.** Data with no loop-closing is wasted goodwill.
