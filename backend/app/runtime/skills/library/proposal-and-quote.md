---
name: proposal-and-quote
title: Proposal & Quote
description: Produce a clear, honest proposal and price quote that a buyer can approve without back-and-forth.
roles: growth, ceo, finance
---
# Proposal & Quote

A proposal should make saying yes easy: the buyer's problem restated, the scope, the
price, and the terms — with no surprises. This playbook builds one grounded in real pricing.

## Prerequisite
Discovery complete (quantified pain + decision process known). Pricing must come from the
company's actual pricing model, not an invented number — read it via `get_company_playbook`
or `read_company_file`; if none exists, `request_decision` from the CEO/finance role.

## Workflow
1. **Restate the problem and outcome** in the buyer's words, with the cost-of-pain number
   from discovery. This is the value anchor for the price.
2. **Scope precisely.** List what's included and — just as important — what's out of scope,
   so expectations are set before signature.
3. **Price from the model.** Pull the real price/tier. If the deal needs a non-standard
   discount or term, `request_decision` (or `request_budget` if it affects margin targets)
   rather than freelancing terms.
4. **Draft the document.** `draft_document` with sections: Problem, Proposed solution,
   Scope, Pricing & terms, Timeline, Next step. Keep it under ~2 pages.
5. **Record the deal economics.** `crm_save_deal`/`update_deal` with amount and stage
   `proposal`; `write_memory` (type `result`) the quoted price and any concessions.
6. **Send and track.** Deliver via `send_email` (or the buyer's channel); `schedule_followup`
   for 2–3 business days; `crm_log_activity`.

## Decision framework — discounting
Discount only for something in return (multi-year, case study, upfront payment). A discount
given for nothing trains the buyer to expect more and erodes margin — escalate via `request_decision`.

## Definition of done
- Price traces to the real pricing model or an approved exception.
- Out-of-scope explicitly stated.
- Deal amount and any concession recorded; follow-up scheduled.

## Common failure modes
- **Invented pricing.** Never quote a number the company hasn't approved.
- **Fuzzy scope.** Undefined scope becomes unpaid work and disputes later.
- **Sending and forgetting.** Proposals rot without a dated follow-up.
