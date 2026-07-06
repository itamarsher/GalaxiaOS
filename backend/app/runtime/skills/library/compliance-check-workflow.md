---
name: compliance-check-workflow
title: Compliance Check Workflow
description: Run a structured compliance check on an action or artifact before it creates legal or regulatory exposure.
roles: governance, auditor
---
# Compliance Check Workflow

Compliance failures are expensive and often irreversible. This playbook runs a structured check on an
action, feature, or artifact before it ships — catching exposure while it's still cheap to fix.

## Workflow
1. **Identify what applies.** What is being checked, and which obligations are relevant — data privacy,
   payments, marketing/consumer, industry-specific (`regulatory-landscape-scan`, `list_data_policies`)? Scope
   the check to real, applicable rules, not a generic checklist.
2. **Run the check against specifics.** `check_compliance` and compare the action to each concrete
   obligation: is consent obtained, are disclosures present, is data handled per policy, are claims substantiated?
3. **Assess exposure on gaps.** For each gap, how likely and how severe is the consequence (fine, shutdown,
   liability, reputational)? Rank so effort goes where exposure is greatest.
4. **Know the boundary.** This is a structured check, not legal advice. For material or ambiguous issues,
   `flag_legal_risk` and `request_user_action` to involve qualified counsel — an agent must not adjudicate real
   legal risk alone.
5. **Gate the action.** A material unresolved compliance gap is a stop, not a warning — block the launch/send
   (`product-launch-checklist`, `external-communication-review`) until resolved. Cosmetic gaps can fast-follow.
6. **Document.** `write_memory` (type `result`) the check, findings, and decisions; `create_report` for the
   record. Compliance decisions need an audit trail.

## Decision framework — block on material exposure
When a real, material compliance gap exists, the default is stop-and-resolve, not proceed-and-hope.
Under uncertainty, escalate to counsel. The asymmetry is stark: a delay is recoverable; a violation often isn't.

## Definition of done
- Applicable obligations scoped; action checked against each specific; gaps assessed for exposure and ranked.
- Material/ambiguous items escalated to counsel; material gaps gated the action; check documented for the record.

## Common failure modes
- **Generic checklist theater.** Checking boxes unrelated to the real applicable rules.
- **Agent-as-lawyer.** Adjudicating material legal risk without counsel.
- **Warn-but-proceed.** Flagging a material gap yet letting the action ship anyway.
