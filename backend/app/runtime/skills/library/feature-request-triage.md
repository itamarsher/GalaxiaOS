---
name: feature-request-triage
title: Feature Request Triage
description: Turn a stream of feature requests into structured, deduplicated signal for the roadmap.
roles: product
---
# Feature Request Triage

Raw feature requests are noisy and repetitive. This playbook converts them into clean signal:
deduplicated, tied to problems, and weighted by real demand.

## Workflow
1. **Collect from all sources.** `list_feature_requests`, support threads, sales notes
   (`crm_contact_timeline`), and community. Requests scattered across channels hide real demand.
2. **Translate request → problem.** Users request solutions; capture the underlying problem
   ("export to CSV" → "I need my data in my own tools"). The problem is what you prioritize.
3. **Deduplicate and count.** Merge requests describing the same problem; the count is a demand
   signal. `write_memory` (type `learning`) the top clustered problems with counts.
4. **Weight by more than volume.** Factor in requester value (a churning enterprise account vs.
   many free users) and strategic fit. Volume alone over-weights vocal minorities.
5. **Route.** Validated, high-signal problems → `promote_feature_request` into the prioritization
   queue (`feature-prioritization`). Out-of-scope → a kind decline logged in the request.
6. **Close the loop.** Tell requesters where their input landed (shipped, planned, declined-and-why).
   `send_notification` / `crm_log_activity`. Silence teaches users to stop giving feedback.

## Decision framework — solution vs. problem
Never prioritize the literal request; prioritize the problem behind it. Multiple requests often
share one problem a single better solution solves.

## Definition of done
- Requests collected across sources, translated to problems, deduped with counts.
- Weighted by value and fit; routed; requesters informed of the outcome.

## Common failure modes
- **Building literal requests.** You ship ten half-solutions instead of one good one.
- **Volume-only weighting.** Over-serves the loud, under-serves high-value quiet accounts.
- **Feedback black hole.** Not closing the loop kills future signal.
