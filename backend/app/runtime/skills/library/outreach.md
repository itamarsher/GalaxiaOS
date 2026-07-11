---
name: outreach
title: Outreach.io
description: Build, A/B test, or run outbound sales sequences and cadences in Outreach.io when engaging prospects through multi-touch email/call plays.
roles: growth
---
# Outreach.io

Outreach.io is the fleet's sales-engagement platform — multi-touch sequences, cadence analytics, and
sentiment tracking. This skill is the ABOS-adapted path to using it well: **connect it as a tool
first, never assume it's wired**, then sequence compliantly and let the data prune what doesn't work.
Every touch and reply is logged back to the ABOS CRM (`crm_log_activity`, `update_deal`).

## Connect before you sequence
1. **Find the tool.** `discover_tools` with query `outreach`; it exposes as `mcp__outreach__*` once the
   founder has connected it. Load what you need with `use_tool` (add prospects, start a sequence).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Outreach in
   Settings (OAuth app or MCP server). Never invent prospects or "sent"/"replied" counts — fabricated
   engagement corrupts every downstream metric.
3. **Least privilege + egress.** Loading prospect data into Outreach is data egress; if sensitive data
   flows out, `check_compliance` / `list_data_policies` first.

## Sequence compliantly and test one thing at a time
4. **Outbound is gated external comms.** Every sequence is indexed into the external-comms log and may
   need founder sign-off — respect the approval gate. `check_compliance` for opt-out/CAN-SPAM/GDPR
   before launch, honor unsubscribes globally, and keep daily send limits conservative to protect
   deliverability.
5. **Multi-touch, short, personalized.** Over 30% of replies come after the third attempt, so don't
   end sequences early; keep emails ~400-600 characters (intro, pain, CTA, signature).
6. **A/B test a single variable.** Change subject OR send-time, never both; give each variant ~100-150
   prospects (200-300 data points) before reading results. Document each test so learning compounds.
7. **Watch sentiment and opt-outs as signals.** A step with elevated opt-outs or negative sentiment is
   broken — fix or cut it. Review sequences ~every six months and prune underperformers.

## File the deliverable and record it
8. **Log outcomes to CRM.** `crm_log_activity` real touches and replies; `update_deal` on positive
   sentiment; `save_file` the cadence report (category `artifact`) with the Outreach link.
9. **Record + hand off.** `write_memory` (type `result`) what worked; `record_metric` for reply and
   meeting rates; `report_result` or `schedule_followup` on warm replies.

## Definition of done
- Outreach confirmed connected (or escalated, never faked); egress checked.
- Sequence passed the approval + compliance gate; opt-outs honored; send limits respected.
- One-variable A/B tests with adequate sample; real outcomes logged to CRM; nothing fabricated.

## Common failure modes
- **Phantom engagement.** Reporting sends/replies when Outreach was never connected — escalate instead.
- **Skipping the comms gate.** Blasting a cadence without compliance check, opt-out handling, or sign-off.
- **Confounded A/B tests.** Changing two variables at once, so no result is trustworthy.
