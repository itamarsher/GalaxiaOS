---
name: carta
title: Carta
description: Update the cap table, issue option grants, refresh a 409A, record a SAFE, or prep board consents in Carta when equity or ownership changes.
roles: finance, ceo
---
# Carta

Carta is the fleet's cap table of record — shares, options, SAFEs, vesting, and 409A valuations. Entries
here define who owns the company, so the ABOS-adapted principle is: **connect it as a tool first, never
assume it's wired, and never invent an equity fact.** Every entry must trace to an executed document;
a fabricated grant or ownership number is a legal misstatement.

## Connect before you touch the cap table
1. **Find the tool.** `discover_tools` query `carta`; it exposes as `mcp__carta__*` once the founder
   connects it. Load what you need with `use_tool`.
2. **Not connected? Escalate — don't fake it.** `request_user_action` for the founder to connect Carta
   in Settings. Never invent a grant, ownership percentage, or 409A price.
3. **Equity changes are gated and legal.** Grants, SAFEs, and repricings need proper approval —
   `request_decision` (founder/board sign-off) and `flag_legal_risk` / `check_compliance` before any
   entry. Carta stores the data; it does not verify the approval exists.

## Keep the cap table clean like a pro
4. **Every entry traces to an executed doc.** Charter, stock plan, board/stockholder consents, SAFEs,
   grant agreements. Enter into Carta only after documents are signed, then spot-check Carta against the
   executed paperwork — Carta can't confirm a grant was validly approved.
5. **Reconcile authorized vs issued vs reserved.** Confirm the plan has capacity before any grant, and
   that authorized shares support what's issued. Re-model SAFEs/notes (cap, discount) so pro-formas hold.
6. **Refresh the 409A after every round.** A new priced round makes the old fair market value stale;
   refresh within a few weeks so option strike prices are defensible. Grants issued under a stale 409A
   are a tax exposure.
7. **Grants: capacity, approval, terms, acceptance.** Confirm plan capacity and board approval, set a
   compliant strike at current FMV, and match vesting/cliff/acceleration to the agreement before Carta
   sends the offer and collects acceptance.

## Record and file it
8. **File the source docs and exports.** `save_file` executed consents, SAFEs, grant agreements, and the
   409A report (category `financial`) — the durable evidence behind every Carta entry.
9. **Report.** `write_memory` (type `result`) the change and doc links; `record_metric` on dilution/pool
   remaining where useful, then `report_result`.

## Definition of done
- Carta confirmed connected (or escalated, never faked); every equity change gated by decision + legal check.
- Entries trace to executed docs; authorized/issued/reserved reconciled; 409A current.
- Source documents and 409A filed via `save_file`, outcome recorded.

## Common failure modes
- **Phantom grant.** Recording equity Carta/legal never approved — trace to an executed doc or escalate.
- **Stale 409A.** Issuing options under an out-of-date valuation after a round, creating tax exposure.
- **Entry before signature.** Updating Carta ahead of executed consents, so the cap table won't survive diligence.
