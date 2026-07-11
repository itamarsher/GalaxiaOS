---
name: paypal
title: PayPal
description: Take checkout payments, send payouts, or handle disputes and chargebacks in PayPal — with webhooks and sandbox.
roles: finance
---
# PayPal

PayPal is the fleet's checkout-and-payouts rail — accept payments, disburse payouts, and manage disputes.
The ABOS-adapted rule: **connect it as a tool first, never assume it's wired**, and because payouts move
real money out irreversibly, **sandbox first, gate every disbursement, and never fabricate a payment**.

## Connect before you transact
1. **Find the tool.** `discover_tools` with query `paypal`; it exposes as `mcp__paypal__*` once the founder
   connects it. Load what you need with `use_tool` (create order, payout, read dispute).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect PayPal in
   Settings (client ID + secret). Never invent a transaction ID, payout, or dispute outcome — a phantom
   payment is worse than none. If the capability can't exist yet, `request_capability`.
3. **Gate the money.** A payout leaves the account and is hard to recover. `request_budget` before a payout
   batch and `request_decision` for large or first-time recipients.

## Integrate the way pros do
4. **Sandbox before live.** Run real sandbox buyer/seller transactions and confirm your handler receives,
   verifies, and processes each event before going live. Keep separate webhook IDs/URLs for sandbox vs prod.
5. **Webhooks, not IPN — verified.** Use REST webhooks (IPN is legacy/deprecated); always verify the
   RSA-SHA256 signature so a spoofed event can't trigger a fake confirmation or unauthorized refund.
6. **Return 2xx, expect retries.** Any non-2xx makes PayPal retry up to 25 times over 3 days, so make
   handlers idempotent — dedupe on event ID or you'll double-process a payment.
7. **Handle disputes fast.** Subscribe to `CUSTOMER.DISPUTE.*` events and respond within PayPal's window
   with evidence; a missed deadline is an automatic loss. Account for PayPal fees in reconciliation.

## Mirror it in ABOS and file it
8. **Record every movement.** `record_transaction` payments and payouts (net of fees) and `read_financials`
   to reconcile against the real PayPal balance — mirror actuals, never estimate.
9. **File the trail.** `save_file` settlement reports and dispute evidence (category `financial`) with the
   PayPal link; `write_memory` (type `result`) and `report_result`. `flag_legal_risk` on chargeback patterns.

## Definition of done
- PayPal confirmed connected (or escalated, never faked); payout batches budgeted and, if large, decided.
- Sandbox-tested, webhooks verified and idempotent, disputes answered within window.
- Payments/payouts recorded net of fees, reports `save_file`d (financial), outcome recorded.

## Common failure modes
- **Phantom payment.** Claiming a payout or sale when PayPal was never connected — escalate instead.
- **Unverified webhook.** Trusting an unsigned event, letting a spoofed payload confirm a fake payment.
- **Missed dispute window.** Failing to submit evidence in time and forfeiting the chargeback automatically.
