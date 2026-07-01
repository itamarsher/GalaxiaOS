---
name: partnership-development
title: Partnership Development
description: Evaluate and structure a strategic partnership so it creates real, mutual, measurable value.
roles: ceo, growth
---
# Partnership Development

Partnerships promise leverage and often deliver overhead. This playbook evaluates and structures one
so it creates real mutual value — with clear terms and a way to measure whether it's working.

## Workflow
1. **Define the strategic rationale.** What specific outcome would this partnership create that we
   can't cheaply get alone — distribution, capability, credibility? A partnership without a clear "why"
   becomes a time sink. `write_memory` (type `experiment`) the goal and success metric.
2. **Assess mutual fit.** A durable partnership serves both sides. Articulate what we gain AND what
   they gain; if it's lopsided, it won't last. `web_search` to vet the partner's reputation and stability.
3. **Screen the risks.** Reputational association, exclusivity, IP/data sharing, dependency.
   `flag_legal_risk` and `check_compliance` on anything material; involve counsel via `request_user_action`
   for real contracts — don't sign terms an agent can't properly assess.
4. **Start small and testable.** Prefer a limited pilot with clear success criteria over a sweeping
   exclusive deal. Prove value before deepening; `request_decision` for the founder on material commitments.
5. **Structure clear terms.** Who does what, how value/revenue is shared, how it's measured, and how
   either side exits. Ambiguity breeds disputes.
6. **Manage and measure.** `crm_save_deal` / `crm_log_activity` to track it; `record_metric` against the
   success metric; `write_memory` (type `result`) whether it's earning its overhead.

## Decision framework — pilot before you marry
Test partnerships small and measurable before big or exclusive commitments. The cost of a failed
pilot is small; the cost of a bad exclusive deal can be strategic.

## Definition of done
- Clear rationale and success metric; mutual value articulated; risks screened and material terms to counsel.
- Structured as a testable pilot with clear terms and exit; measured against the metric.

## Common failure modes
- **Vanity partnerships.** Impressive logos, no real value, ongoing overhead.
- **Lopsided deals.** If only one side benefits, the other disengages.
- **Big exclusive bets untested.** Pilot first; exclusivity is easy to enter, hard to exit.
