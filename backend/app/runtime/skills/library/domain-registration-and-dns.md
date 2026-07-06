---
name: domain-registration-and-dns
title: Domain Registration & DNS
description: Register a domain and configure DNS correctly, treating it as real, budgeted, irreversible spend.
roles: platform, growth
---
# Domain Registration & DNS

A domain is real money and real infrastructure. This playbook registers one and wires DNS correctly —
budget-first, because registration is an irreversible external charge.

## Workflow
1. **Confirm the need and name.** What is this domain for, and is the exact name decided? Check
   availability and avoid trademark conflicts (`web_search`, `flag_legal_risk`) — a name that infringes
   is a liability, not a brand.
2. **Budget first — it's irreversible.** Registration charges real money through the CostMeter.
   `request_budget` and confirm the reserve clears BEFORE the buy; the registrar must fail before the
   irreversible call if the balance is short, never after.
3. **Register.** Use `register_domain`. If it reports the capability/registrar is unsupported, STOP and
   `request_capability` — do not claim a domain is registered when it isn't.
4. **Configure DNS.** `connect_domain` to point it where it needs to go (site, mail). Get records right —
   a typo in DNS means an outage or lost mail. Verify propagation before declaring done.
5. **Set up the essentials.** Ensure HTTPS and, if the domain sends mail, the sender records (so email
   lands, not spam). `dispatch_task` to whatever handles certs/mail if not built in; `request_capability` if unsupported.
6. **Record and diarize renewal.** `record_transaction` the cost; `log_ops_event`; `write_memory` (type
   `result`) the domain and its renewal date. A lapsed domain can be lost permanently — schedule the renewal.

## Decision framework — reserve before you commit
Never trigger an irreversible external purchase before the budget reserve is confirmed. The order is
always: decide the name → reserve budget → buy → configure → verify. Reversing that order risks unbudgeted
spend the CostMeter exists to prevent.

## Definition of done
- Name decided and conflict-checked; budget reserved before purchase; domain registered (or capability requested).
- DNS/HTTPS/mail configured and verified; cost recorded; renewal diarized.

## Common failure modes
- **Buying before reserving budget.** Irreversible spend outside the guardrail.
- **DNS typos.** A wrong record causes outages or lost mail.
- **Forgotten renewal.** A lapsed domain can be lost to a squatter permanently.
