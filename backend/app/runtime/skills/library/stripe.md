---
name: stripe
title: Stripe
description: Take payments, spin up subscriptions or Billing, handle webhooks, or reconcile revenue in Stripe when money actually moves through the product.
roles: finance
---
# Stripe

Stripe is where the fleet moves real money — charges, subscriptions, payouts, refunds. Every call is
metered spend against a real customer, so the ABOS-adapted principle is: **connect it as a tool first,
never assume it's wired, and never invent a payment.** Read real Stripe data or escalate; a fabricated
charge or balance is a false financial record.

## Connect before you charge
1. **Find the tool.** `discover_tools` query `stripe`; it exposes as `mcp__stripe__*` once the founder
   connects it. Load what you need with `use_tool`.
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to add the Stripe
   MCP server / restricted API key in Settings. Never invent a payment link, invoice, or balance.
3. **Money is gated.** Any live charge, refund, or payout is metered and irreversible — `request_budget`
   before material spend and `request_decision` (founder sign-off) before moving real money.

## Use Stripe like a pro
4. **Test mode first, always.** Build and verify in a sandbox (test key) before a single live call. Test
   and live use different keys, webhook URLs, and signing secrets — never cross them.
5. **Idempotency key on every POST.** Attach a UUID (or customer+order id) to charges and mutations so a
   retry after a network error can't double-charge. Never put PII in the key.
6. **Webhooks are the source of truth, not the redirect.** Verify the signature, dedupe on `event.id`,
   and make handlers order-independent — fulfillment, entitlement, and accounting transitions happen on
   the webhook, not the browser callback. Let Radar screen fraud; review flagged charges before capture.
7. **Billing for recurring revenue.** Use Subscriptions/Billing for anything that renews — don't
   hand-roll invoicing. Reconcile Stripe payouts against the bank and the ledger every period.

## Record it in the ledger
8. **Mirror every real transaction.** `record_transaction` for charges/refunds and `generate_invoice`
   where ABOS owns billing; `read_financials` to reconcile. `save_file` payout/statement exports
   (category `financial`). Tax/regulatory handling on payments → `check_compliance`.
9. **Report.** `record_metric` revenue/MRR, `write_memory` (type `result`), then `report_result`.

## Definition of done
- Stripe confirmed connected (or escalated, never faked); live money gated by budget/decision.
- Built in test mode, idempotency keys set, webhooks signature-verified and deduped.
- Transactions mirrored via `record_transaction`, reconciled, statements filed, outcome recorded.

## Common failure modes
- **Phantom payment.** Reporting a charge or balance Stripe never processed — read real data or escalate.
- **Double charge.** POST without an idempotency key, so a retry bills the customer twice.
- **Trusting the redirect.** Fulfilling on the client callback instead of the verified webhook.
