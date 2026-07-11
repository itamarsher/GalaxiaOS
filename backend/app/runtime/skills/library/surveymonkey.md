---
name: surveymonkey
title: SurveyMonkey
description: Design a survey or read its results — customer feedback, NPS/CSAT, market research — when the questionnaire lives (or should live) in SurveyMonkey.
roles: research, product
---
# SurveyMonkey

SurveyMonkey is the fleet's survey platform: questionnaire design, skip/branching logic, distribution,
and NPS/CSAT reporting. This skill is the ABOS-adapted path to using it well: **connect it as a tool
first, never assume it's wired**, then write unbiased questions and never invent a response.

## Connect before you field
1. **Find the tool.** `discover_tools` with query `surveymonkey`; it exposes as
   `mcp__surveymonkey__*` once the founder has connected it. Load what you need with `use_tool`
   (surveys, collectors, responses).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect
   SurveyMonkey in Settings (MCP server or API token). If it can't exist yet, `request_capability`.
3. **Never fabricate responses.** Every reported figure must come from real collected data — if none
   exist yet, say so. A phantom NPS is worse than none. A survey invite is outbound (external-comms log,
   possible sign-off); responses are personal data — `check_compliance` / `list_data_policies` first.

## Design so the data is valid
4. **Kill bias in the wording.** Avoid leading, loaded, and double-barreled questions; use plain,
   parallel language and balanced scales (equal positive/negative options). Ambiguous wording is
   measurement error you can't fix after the fact.
5. **Keep it short, use logic.** Aim for ~10-15 questions — completion falls sharply as length grows.
   Use skip/branching logic so respondents only see what's relevant, and randomize answer order where
   position bias matters.
6. **Use NPS/CSAT as designed.** NPS = %promoters (9-10) − %detractors (0-6) on the 0-10 recommend
   scale; CSAT = % satisfied on a labeled 5-point scale. Don't relabel or re-bucket the scale, or the
   score stops comparing to any benchmark.
7. **Mind the sample and significance.** A convenience sample isn't the population — note who was
   reached and the response count. Small n and self-selection skew results; check statistical
   significance before calling one segment different from another, and flag the caveat if you can't.

## File the deliverable and record it
8. **File the artifact.** `save_file` the survey design and the results summary (category `artifact`)
   with the SurveyMonkey link — durable and shareable, unlike agent memory.
9. **Record + hand off.** `record_metric` NPS/CSAT and n, `write_memory` (type `result`/`learning`)
   the finding with its caveats, then `report_result` or `dispatch_task` to act on it.

## Definition of done
- SurveyMonkey confirmed connected (or escalated, never faked); invite gate and response egress checked.
- Questions unbiased and short with logic; NPS/CSAT scales standard; sample and significance noted.
- Design/results `save_file`d with link, real metrics recorded, finding handed off.

## Common failure modes
- **Fabricated result.** Reporting an NPS/CSAT with no real responses behind it — escalate instead.
- **Leading questions.** Wording that steers the answer, producing confident but meaningless data.
- **Overclaiming on a bad sample.** Treating a small, self-selected group as the whole population.
