---
name: product-discovery-interviews
title: Product Discovery Interviews
description: Run customer interviews that uncover real problems and unmet needs without leading the witness.
roles: product, research, ceo
---
# Product Discovery Interviews

Discovery interviews de-risk what you build. Done well they reveal real problems; done badly
they confirm your biases. This playbook keeps them honest and useful.

## Workflow
1. **State the learning goal.** What decision will these interviews inform? "Should we build X?"
   is weaker than "What is the hardest part of doing Y today?" — ask about problems, not features.
2. **Recruit the right people.** `crm_find_contacts` for users in the target segment; aim for
   5–8 (patterns emerge fast). Talk to people who have the problem, not just friendly customers.
3. **Write non-leading questions.** Ask about past behavior, not hypotheticals: "Tell me about
   the last time you…" beats "Would you use…". People predict their future behavior badly and
   flatter your idea to be nice.
4. **Interview and capture.** Listen for the problem, its frequency, its cost, and current
   workarounds. Record verbatim quotes — `write_memory` (type `learning`) per interview, with the
   raw language (positioning and copy will reuse it).
5. **Synthesize across interviews.** Look for repeated problems, not one loud request. `write_memory`
   (type `result`) the 2–3 validated problems and the evidence count behind each.
6. **Feed the pipeline.** Route validated problems to `feature-prioritization`; log emergent
   requests in `list_feature_requests`.

## Decision framework — signal vs. noise
A problem mentioned unprompted by many is signal. A feature requested by one is a data point.
Build for validated problems, not the loudest voice.

## Definition of done
- Learning goal set; 5–8 in-segment interviews with non-leading, behavior-based questions.
- Verbatim quotes captured; validated problems synthesized with evidence counts.

## Common failure modes
- **Leading questions.** "Would you love a feature that…" gets a polite yes and teaches nothing.
- **Pitching, not listening.** Discovery is diagnosis; save the demo.
- **Building for n=1.** One request isn't a validated problem.
