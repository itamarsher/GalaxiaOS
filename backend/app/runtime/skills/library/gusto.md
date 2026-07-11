---
name: gusto
title: Gusto
description: Run payroll, file payroll taxes, onboard employees or contractors, manage benefits, or hit a compliance deadline in Gusto when the company pays people there.
roles: finance
---
# Gusto

Gusto is how the fleet pays its people — payroll runs, tax filings, contractor and employee onboarding,
benefits. Each run debits real cash and creates a tax obligation, so the ABOS-adapted principle is:
**connect it as a tool first, never assume it's wired, and never invent a payroll.** Read real pay data
or escalate; a fabricated run or filing is a false financial and legal record.

## Connect before you pay people
1. **Find the tool.** `discover_tools` query `gusto`; it exposes as `mcp__gusto__*` once the founder
   connects it. Load what you need with `use_tool`.
2. **Not connected? Escalate — don't fake it.** `request_user_action` for the founder to connect Gusto
   (OAuth) in Settings. Never invent a pay run, tax filing, or W-2/1099.
3. **Payroll is gated.** A run moves real money and can't be clawed back easily — `request_budget` for
   the payroll amount and `request_decision` (founder sign-off) before submitting any run.

## Run payroll like a pro
4. **Classify correctly — employee vs contractor.** Set the classification at onboarding; it drives W-2
   vs 1099, tax withholding, and filings. Misclassification is a legal liability — route any doubt
   through `check_compliance` / `flag_legal_risk`.
5. **Collect onboarding forms before first pay.** W-4 (withholding) and I-9 (work authorization) for
   employees; W-9 for contractors. Gusto handles new-hire state reporting — respect the deadline
   (often 7-20 days from hire).
6. **Let Gusto file taxes, but verify.** Gusto calculates, deducts, and files federal/state forms (941/944,
   940/FUTA, W-2s, 1099s) each period. Confirm bank funding clears before the run and reconcile the tax
   debits — a bounced payroll means missed filings and penalties.
7. **Benefits and ACA.** Employer benefit contributions flow through payroll; if you offer health
   coverage, it must meet ACA rules. Heed Gusto's deadline notifications — don't let one slip.

## Record and file it
8. **Mirror and export.** `record_transaction` for each payroll debit and tax payment so ABOS mirrors
   the ledger; `read_financials` to reconcile. `save_file` pay stubs, filings, W-2/1099 (category
   `financial`).
9. **Report.** `record_metric` on payroll burn/headcount cost, `write_memory` (type `result`), then
   `report_result`.

## Definition of done
- Gusto confirmed connected (or escalated, never faked); each run gated by budget/decision.
- Workers classified correctly, onboarding forms collected, tax filings verified and funded.
- Runs mirrored via `record_transaction`, filings filed, outcome recorded.

## Common failure modes
- **Phantom payroll.** Reporting a run or filing Gusto never made — read real data or escalate.
- **Misclassification.** Paying a real employee as a 1099 contractor, creating tax and legal liability.
- **Unfunded run.** Submitting payroll before the bank clears, bouncing pay and missing tax deadlines.
