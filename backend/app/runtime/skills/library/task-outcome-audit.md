---
name: task-outcome-audit
title: Task Outcome Audit
description: Independently verify that completed tasks actually achieved their stated outcome, not just reported success.
roles: auditor, governance
---
# Task Outcome Audit

Agents can report success without achieving it — through optimism, error, or shortcuts. This playbook
independently verifies that completed work actually delivered its stated outcome, keeping the fleet honest.

## Workflow
1. **Select what to audit.** Sample high-stakes, external-facing, or outcome-critical tasks, plus a random
   sample of routine ones. Auditing everything is wasteful; auditing nothing is negligent — sample by risk.
2. **Recover the claimed outcome.** For each task, what was it supposed to achieve and what did it report
   (`report_result`, `collect_results`, `write_memory` history)? Establish the claim before testing it.
3. **Verify against evidence, not the report.** Check the real artifacts and state: was the email actually
   sent, the metric actually moved, the deliverable actually produced and correct? A task's own success report
   is a claim to verify, not proof.
4. **Watch for the specific failure modes:** fabricated results (claiming an action that never happened),
   shortcut completion (marking done without meeting the criteria), and hallucinated facts in outputs. These
   are exactly what independent audit exists to catch.
5. **Flag and route.** `audit_task` the failures with specifics; `flag_legal_risk` if a false claim reached
   outside the company; `retry_task` or `dispatch_task` genuine gaps. `request_decision` on systemic problems.
6. **Report and improve.** `create_report` (kind `status_report`); `write_memory` (type `learning`) recurring
   failure patterns — feed them into governance policy and reputation signals so the fleet's trust scores reflect reality.

## Decision framework — evidence over reports
Never accept 'done' as proof of done. The audit's job is to check the claim against reality, especially for
irreversible or external outcomes. A fleet that self-reports unaudited drifts toward confident wrongness.

## Definition of done
- Tasks sampled by risk; claimed outcomes recovered; verified against real evidence, not self-reports.
- Fabrication/shortcut/hallucination specifically checked; failures flagged and routed; patterns fed back to governance.

## Common failure modes
- **Trusting the success report.** Accepting the claim instead of verifying the outcome.
- **Auditing only routine work.** Missing the high-stakes tasks where failure hurts most.
- **No feedback loop.** Findings that don't update policy or reputation let the same failures recur.
