---
name: wise
title: Wise
description: Hold multi-currency balances, send international transfers, or run batch payouts at the mid-market rate in Wise.
roles: finance
---
# Wise

Wise is the fleet's international-money rail — multi-currency accounts, cross-border transfers at the
mid-market rate, and batch payouts. The ABOS-adapted rule: **connect it as a tool first, never assume it's
wired**, and because transfers move real money across borders irreversibly, **gate the send and mirror the
actual rate, never a guessed one**.

## Connect before you send
1. **Find the tool.** `discover_tools` with query `wise`; it exposes as `mcp__wise__*` once the founder
   connects it. Load what you need with `use_tool` (create quote, recipient, transfer, batch group).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Wise in
   Settings (API token + profile). Never invent a transfer, balance, or exchange rate — a phantom transfer
   is worse than none. If the capability can't exist yet, `request_capability`.
3. **Gate the money.** A cross-border transfer can't be recalled. `request_budget` before a payout run and
   `request_decision` for large or first-time recipients.

## Move money the way pros do
4. **Quote, then transfer.** Always create a quote first so the mid-market rate and Wise fee are shown
   separately — record both. Fund promptly to lock that day's rate; a stale quote re-prices.
5. **Validate recipient details hard.** Wrong IBAN/routing/account details fail or delay payments; verify
   out-of-band before sending, and treat a changed-details request as a fraud signal (`flag_legal_risk`).
6. **Batch for one control point.** Group up to ~1,000 transfers into a batch group under one reference and
   fund once from the multi-currency balance — a single approvable, auditable run beats scattered wires.
7. **Hold vs convert deliberately.** Hold balances in the currencies you'll spend to avoid double
   conversion; convert only when the rate and need justify it.

## Mirror it in ABOS and file it
8. **Record the real numbers.** `record_transaction` each transfer with the actual rate and fee, and
   `read_financials` to reconcile multi-currency balances — mirror Wise, never estimate FX.
9. **File the trail.** `save_file` transfer confirmations and payout reports (category `financial`) with the
   Wise link; `write_memory` (type `result`) and `report_result`. For cross-border/tax, `check_compliance`.

## Definition of done
- Wise confirmed connected (or escalated, never faked); payout runs budgeted and, if large, decided.
- Quote captured (rate + fee), recipient details verified, batches used for a single control point.
- Transfers recorded at actual rate/fee, confirmations `save_file`d (financial), outcome recorded.

## Common failure modes
- **Phantom transfer.** Reporting a payment sent when Wise was never connected — escalate instead.
- **Wrong recipient details.** Sending on unverified or spoofed bank details, losing or delaying the funds.
- **Guessed FX.** Recording an estimated rate instead of the actual quote, so the books don't reconcile.
