---
name: brex
title: Brex
description: Issue corporate cards, set spend limits or policies, capture receipts, or sync card expenses to the books in Brex.
roles: finance
---
# Brex

Brex is the fleet's corporate-card and spend-control layer — virtual cards, budgets, receipt matching,
and accounting sync. The ABOS-adapted rule: **connect it as a tool first, never assume it's wired**, and
because cards move real money, **treat every issuance and limit change as metered spend**, not a config edit.

## Connect before you spend
1. **Find the tool.** `discover_tools` with query `brex`; it exposes as `mcp__brex__*` once the founder
   connects it. Load what you need with `use_tool` (create card, set limit, read transactions).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Brex in
   Settings (API token). Never invent a card number, balance, or transaction — a phantom payment is worse
   than none. If the capability can't exist yet, `request_capability`.
3. **Gate the money.** Issuing a card or raising a limit is real spend exposure. `request_budget` before
   provisioning card capacity, and `request_decision` for anything large or hard to reverse.

## Run spend controls the way pros do
4. **Virtual card per vendor/purpose, tight limits.** Issue a scoped virtual card with a hard cap and
   category/merchant restrictions rather than one shared card. Auto-decline over the cap — the control is
   the limit, not after-the-fact review.
5. **Tiered approvals by amount.** Wire budgets and multi-level approval so routine spend flows and large
   purchases require sign-off. Encode the thresholds from `get_company_playbook`, not ad hoc.
6. **Let Brex match receipts.** Rely on Brex AI receipt matching and enforce a submit-within-a-week
   deadline so records stay current; unmatched transactions are the audit gap to chase.
7. **Sync to the books.** Map categories to the GL so card spend reconciles cleanly into
   QuickBooks/NetSuite; a miscoded transaction is a close-process problem later.

## Mirror it in ABOS and file it
8. **Record every movement.** `record_transaction` each material card charge and `read_financials` to
   reconcile against real balances — the ledger mirrors Brex, it never guesses.
9. **File statements.** `save_file` exported statements and receipts (category `financial`) with the Brex
   link; `write_memory` (type `result`) and `report_result`. For tax coding, `check_compliance`.

## Definition of done
- Brex confirmed connected (or escalated, never faked); issuance/limit changes budgeted and, if large, decided.
- Scoped cards with hard limits, tiered approvals, receipts matched and coded to the GL.
- Transactions recorded, statements `save_file`d (financial), outcome recorded.

## Common failure modes
- **Phantom spend.** Reporting a card issued or a charge made when Brex was never connected — escalate instead.
- **Uncapped shared card.** One card with no per-purpose limit turns a mistake into unbounded loss.
- **Unreconciled sync.** Miscoded or unmatched transactions that surface as a mess at month-end close.
