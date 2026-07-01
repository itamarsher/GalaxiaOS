---
name: survey-design-and-analysis
title: Survey Design & Analysis
description: Design surveys that yield unbiased, actionable data and analyze them without over-reading noise.
roles: research, product, data
---
# Survey Design & Analysis

A badly designed survey produces confident garbage. This playbook designs for unbiased signal and
analyzes it honestly — so survey data informs decisions instead of laundering assumptions.

## Workflow
1. **Define the decision and the question.** What will this survey change? Each question must earn
   its place by informing that decision — long surveys with vanity questions get abandoned. `write_memory`
   (type `experiment`) the goal.
2. **Write unbiased questions.** Avoid leading ("How much do you love X?"), double-barreled (two
   questions in one), and vague wording. Prefer behavior over hypotheticals; balance scale options.
3. **Sample deliberately.** Decide who should answer and how many for the result to mean something.
   Know your sampling bias — the people who respond differ from those who don't; don't over-generalize.
4. **Distribute.** `send_email` / `schedule_social_post` to the target sample; keep it short to protect
   completion rate. `crm_log_activity`.
5. **Analyze honestly.** `record_metric` the results; segment (`cohort-analysis`) since averages hide
   splits. Report confidence intervals or caveats for small samples — don't present noise as fact.
6. **Turn into action.** `write_memory` (type `result`) the findings and the one decision they support;
   `create_report` (kind `research_report`). Flag where the data is suggestive but not conclusive.

## Decision framework — signal strength vs. sample
Match the confidence of your claims to your sample size and method. A clear result from a solid
sample can drive a decision; a thin or biased sample can only suggest a hypothesis to test.

## Definition of done
- Tied to a decision; unbiased, non-leading questions; deliberate sample with known bias.
- Analyzed with segmentation and honest caveats; findings turned into a supported decision.

## Common failure modes
- **Leading questions.** Design that confirms your assumption teaches nothing.
- **Over-reading small samples.** Presenting noise as significant finding.
- **Ignoring non-response bias.** Respondents aren't the whole population.
