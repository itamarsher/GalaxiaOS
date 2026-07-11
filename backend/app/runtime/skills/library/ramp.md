---
name: ramp
title: Ramp
description: Issue virtual cards, set spend controls, match receipts, route approvals, or sync spend to accounting in Ramp when company money leaves via cards or bills.
roles: finance
---
# Ramp

Ramp is where the fleet's card and bill spend happens — virtual cards, policies, approvals, and the sync
into the general ledger. Every card issued can spend real money, so the ABOS-adapted principle is:
**connect it as a tool first, never assume it's wired, and never invent a charge.** Read real spend or
escalate; a fabricated transaction is a false financial record.

## Connect before you spend
1. **Find the tool.** `discover_tools` query `ramp`; it exposes as `mcp__ramp__*` once the founder
   connects it. Load what you need with `use_tool`.
2. **Not connected? Escalate — don't fake it.** `request_user_action` for the founder to connect Ramp
   (OAuth / API key) in Settings. Never invent a card, receipt, or transaction.
3. **Spend is gated.** Issuing a card or paying a bill moves real money — `request_budget` before
   material spend and `request_decision` (founder sign-off) before authorizing a payment.

## Control spend like a pro
4. **One virtual card per vendor, locked to that merchant.** Per-vendor cards with a monthly cap and
   merchant lock mean no single card can overspend or be reused elsewhere. Use single-use cards that
   auto-close for one-off purchases.
5. **Set the policy limits at creation.** Cap by transaction, day, or month; restrict by merchant
   category or team. Compliant purchases auto-approve; exceptions flag to finance — build the approval
   flow to mirror who actually signs off on spend.
6. **Require receipts and let OCR match.** Enforce receipt capture (SMS/email OCR) so every charge is
   substantiated; use 2-way matching to tie bills to POs. An unmatched charge is an audit gap.
7. **Map GL coding at card creation, sync per card.** Assign each virtual card a GL code, cost center,
   and department up front so every charge auto-categorizes. Sync bidirectionally to QuickBooks / Xero /
   NetSuite per card, not per statement.

## Record and file it
8. **Mirror and export.** `record_transaction` so ABOS mirrors Ramp spend; `read_financials` to
   reconcile against the ledger. `save_file` statements and receipt exports (category `financial`).
9. **Report.** `record_metric` on spend/burn, `write_memory` (type `result`), then `report_result`.

## Definition of done
- Ramp confirmed connected (or escalated, never faked); card issuance and payments gated by budget/decision.
- Per-vendor cards with limits/merchant locks, receipts enforced, GL coding set at creation.
- Spend mirrored via `record_transaction`, synced and reconciled, statements filed, outcome recorded.

## Common failure modes
- **Phantom charge.** Reporting spend Ramp never made — read real data or escalate.
- **Uncapped card.** Issuing a card with no limit or merchant lock, leaving spend wide open.
- **Unmatched receipts.** Charges with no receipt or GL code, so the accounting sync can't reconcile.
