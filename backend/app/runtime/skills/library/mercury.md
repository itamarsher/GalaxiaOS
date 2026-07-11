---
name: mercury
title: Mercury
description: Move money by ACH or wire, manage treasury and account balances, set card spend limits, or check runway in Mercury when the company banks there.
roles: finance
---
# Mercury

Mercury is the fleet's business bank — checking, savings, ACH/wire rails, treasury, and the real cash
balance the whole company runs on. Every transfer moves real money and clears, so the ABOS-adapted
principle is: **connect it as a tool first, never assume it's wired, and never invent a balance.** Read
the real account or escalate; a fabricated balance or transfer is a false financial record.

## Connect before you move money
1. **Find the tool.** `discover_tools` query `mercury`; it exposes as `mcp__mercury__*` once the founder
   connects it. Load what you need with `use_tool`.
2. **Not connected? Escalate — don't fake it.** `request_user_action` for the founder to add Mercury's
   MCP server / scoped API token in Settings. Never invent a balance, transfer, or transaction.
3. **Moving money is gated.** An ACH or wire out is real and largely irreversible — `request_budget`
   before material spend and `request_decision` (founder sign-off) before initiating any transfer.

## Bank like a pro
4. **Sandbox and scoped tokens first.** Use Mercury's API sandbox to verify a transfer flow before live;
   issue read-only or narrowly scoped tokens so an agent that only needs balances can't move money.
5. **Structure accounts to mirror the plan.** Spin up separate checking/savings for runway reserve, next
   payroll, and department budgets — each with its own number — so cash is visible at a glance instead
   of filtered out of one pile. Treasury (eligible balances) puts idle cash to work.
6. **Lock down cards and ACH pulls.** Issue virtual/physical debit cards with per-card limits, merchant
   restrictions, and one-click freeze; the same limits apply to ACH pulls. Verify wire details out of
   band — wires don't come back.
7. **Watch runway in real time.** Pull balances and transactions via API for live burn and runway rather
   than waiting for statements; alert when runway crosses a threshold.

## Record and file it
8. **Mirror and export.** `record_transaction` for transfers so ABOS mirrors the bank; `read_financials`
   to reconcile cash. `save_file` statements (category `financial`). Large fund movements or regulatory
   questions → `check_compliance` / `flag_legal_risk`.
9. **Report.** `record_metric` on cash/burn/runway, `write_memory` (type `result`), then `report_result`.

## Definition of done
- Mercury confirmed connected (or escalated, never faked); transfers gated by budget/decision.
- Tested in sandbox with scoped tokens, accounts structured, cards limited, wire details verified.
- Transfers mirrored via `record_transaction`, cash reconciled, statements filed, outcome recorded.

## Common failure modes
- **Phantom balance.** Reporting cash or a transfer Mercury never held or sent — read real data or escalate.
- **Over-scoped token.** A money-moving token where a read-only one would do, widening blast radius.
- **Unverified wire.** Sending to unconfirmed details on an irreversible rail.
