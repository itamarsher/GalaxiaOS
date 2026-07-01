---
name: win-loss-analysis
title: Win/Loss Analysis
description: Learn why deals are won and lost from real evidence, and feed it back into product and GTM.
roles: research, growth, product
---
# Win/Loss Analysis

Every closed deal is a lesson the company usually throws away. This playbook extracts why deals
are won and lost from real evidence and turns it into decisions.

## Workflow
1. **Pull a real sample.** `crm_list_deals` for recent wins and losses; `crm_contact_timeline` for
   context. Include both — studying only losses (or only wins) gives a biased picture.
2. **Get the real reason, not the CRM label.** The logged "lost - price" is often a symptom. Where
   possible, ask the buyer directly (`send_email`) — buyers are candid after the decision. Distinguish
   stated from actual reasons.
3. **Categorize patterns.** Group reasons: product gaps, positioning, pricing, sales execution,
   timing, competitor. Count them — one loud loss isn't a pattern; a recurring theme is.
4. **Compare wins vs. losses.** What's different about the deals you win — segment, use case, entry
   point? This reveals your real ICP better than any persona doc.
5. **Route each pattern to an owner.** Product gaps → `feature-prioritization`; positioning →
   `positioning-and-messaging`; pricing → `pricing-experiment`; sales execution → the growth playbooks.
6. **Record and recur.** `write_memory` (type `learning`) the patterns; `create_report`; make this a
   standing analysis, not a one-off — patterns shift as the product and market move.

## Decision framework — pattern over anecdote
Act on recurring, evidence-backed reasons, not the last dramatic loss. Weight by frequency and by
whether it's fixable within our control.

## Definition of done
- Balanced win/loss sample; real reasons distinguished from CRM labels; patterns counted.
- Wins vs. losses compared to sharpen ICP; each pattern routed to an owner; made recurring.

## Common failure modes
- **CRM-label analysis.** "Lost - price" hides the real reason; dig deeper.
- **Losses-only bias.** Wins tell you your ICP; ignoring them skews everything.
- **Anecdote-driven changes.** One memorable loss isn't a mandate.
