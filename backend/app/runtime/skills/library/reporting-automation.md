---
name: reporting-automation
title: Reporting Automation
description: Automate recurring reports so they're consistent, timely, and free the fleet from manual assembly.
roles: data, platform
---
# Reporting Automation

Recurring reports assembled by hand are slow, inconsistent, and error-prone. This playbook automates the
routine ones so they're reliable and timely — freeing the fleet for analysis instead of assembly.

## Workflow
1. **Identify the recurring reports.** Which reports are produced on a regular cadence with the same
   structure (weekly metrics, monthly financials, standup)? These are automation candidates; one-offs are not.
2. **Standardize definitions first.** Automation amplifies whatever it's fed — pin down every metric
   (`kpi-definition`) and source before automating, or you'll reliably produce consistent wrong numbers.
3. **Template the report.** Fixed structure with the narrative sections and metric slots (`metrics-dashboard-setup`,
   `weekly-investor-update`, `weekly-company-standup`). A stable template is what makes automation possible.
4. **Wire the data pull.** `read_metrics` / `read_financials` as sources; ensure the automation reconciles
   against the source of truth (`data-quality-audit`). Build in a freshness/failure check — a silently stale
   report is dangerous.
5. **Automate generation and delivery.** `dispatch_task` / schedule the recurring generation (`create_report`)
   and delivery (`send_notification` / `send_email`) on the cadence. Keep a human/agent review gate for
   judgment-heavy reports (investor update, board deck).
6. **Monitor and maintain.** `record_metric` that reports generate on time and reconcile; `write_memory`
   (type `learning`) failures. Update templates when definitions or needs change.

## Decision framework — automate the routine, keep judgment human
Automate data assembly and formatting; keep interpretation and sensitive external comms under review.
The goal is to remove toil, not to send unreviewed numbers to investors or the board.

## Definition of done
- Recurring reports identified; definitions standardized before automating; templated with stable structure.
- Data wired with reconciliation and freshness checks; generation/delivery scheduled with review gates; monitored.

## Common failure modes
- **Automating on shaky definitions.** Reliably producing consistent wrong numbers.
- **Silent staleness.** An automated report that breaks and delivers old data unnoticed.
- **Auto-sending judgment reports.** Investor/board reports need review, not blind automation.
