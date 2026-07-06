---
name: contract-negotiation-prep
title: Contract Negotiation Prep
description: Prepare for a negotiation by knowing your walk-away, your tradeables, and where legal must weigh in.
roles: growth, ceo, finance
---
# Contract Negotiation Prep

Negotiation goes badly when you improvise on price and terms. This playbook fixes your
limits and your tradeables in advance, and routes real legal risk to the right role.

## Workflow
1. **Know the deal.** `crm_list_deals`/`update_deal` context and the sent proposal
   (`proposal-and-quote` memory). Restate the quoted price and terms.
2. **Set your limits before talking:**
   - *Target* — the outcome you're aiming for.
   - *Walk-away* — the point below which no deal beats this deal. Get CEO/finance sign-off
     via `request_decision` if the walk-away touches margin or precedent.
3. **List tradeables** — things you can give that cost you little but the buyer values
   (payment terms, onboarding help, logo rights) and what you want in return for each.
4. **Screen for legal risk.** Read the buyer's redlines/terms; `check_compliance` for
   anything regulated, and `flag_legal_risk` for unusual liability, IP, data, or indemnity
   clauses. Do not accept legal terms outside your competence — route them.
5. **Plan the sequence.** Concede slowly and in exchange; never give your walk-away away
   early. `write_memory` (type `experiment`) your target, walk-away, and tradeable ladder.
6. **After each round**, `crm_log_activity` and `update_deal`; if terms change materially,
   re-quote via `proposal-and-quote`.

## Decision framework — concede or hold
Concede only when (a) it moves the deal to signature and (b) you get something back. Holding
firm on a well-justified price protects every future deal's price.

## Definition of done
- Target and walk-away set (and approved if they affect margin/precedent).
- Tradeable ladder written with asks attached.
- Legal-risk clauses flagged/routed, not silently accepted.

## Common failure modes
- **No walk-away.** Without it, you'll rationalize any bad deal as "closed."
- **Free concessions.** Every give should buy a get.
- **Playing lawyer.** Unusual liability/IP/data terms go to `flag_legal_risk`, not your judgment.
