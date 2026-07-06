---
name: budget-planning-and-forecast
title: Budget Planning & Forecast
description: Build a grounded budget and forecast tied to objectives and the company's hard spend limit.
roles: finance, ceo
---
# Budget Planning & Forecast

A budget allocates a scarce, hard-capped resource toward objectives. This playbook builds one
grounded in real numbers and the company's actual budget ceiling — no wishful projections.

## Workflow
1. **Establish the constraints.** `read_financials` for current cash, burn, and the hard budget
   cap. The fleet operates under a real ceiling — the budget must fit inside it, not assume more.
2. **Tie spend to objectives.** Allocate by what each objective needs, not by department habit.
   Every line should map to an outcome the company is pursuing.
3. **Forecast revenue conservatively.** Base projections on real pipeline (`crm_list_deals`) and
   historical conversion — not hope. State assumptions explicitly; a forecast is only as good as
   its stated assumptions.
4. **Model scenarios.** Base, downside, and upside. Know the burn and runway under each
   (`runway-and-burn-analysis`). Plan so the downside still survives.
5. **Set guardrails.** Define per-category caps and the triggers that require re-approval
   (`request_budget`). `set_agent_budget` where the plan allocates to specific agents/roles.
6. **Publish and monitor.** `create_report` (kind `financial_report`); `update_company_playbook`
   with the plan; `record_metric` for actual-vs-budget so drift is caught early.

## Decision framework — allocate to leverage
Fund the objectives with the highest expected return per dollar, and protect runway. When
uncertain, keep spend reversible and small until evidence justifies scaling.

## Definition of done
- Budget fits inside the hard cap; every line tied to an objective; assumptions stated.
- Scenarios modeled with survivable downside; guardrails and actual-vs-budget tracking set.

## Common failure modes
- **Budgeting beyond the cap.** The ceiling is real; plans that ignore it aren't plans.
- **Hope-based revenue.** Conservative, assumption-stated forecasts survive contact with reality.
- **No downside plan.** If only the upside survives, the plan is a gamble.
