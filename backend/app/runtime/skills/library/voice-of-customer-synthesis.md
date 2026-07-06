---
name: voice-of-customer-synthesis
title: Voice of Customer Synthesis
description: Aggregate scattered customer feedback into a clear, weighted picture of what customers actually need.
roles: research, product, growth
---
# Voice of Customer Synthesis

Customer signal is scattered across calls, tickets, reviews, and surveys. This playbook synthesizes
it into one weighted, trustworthy picture — so decisions reflect customers, not the loudest email.

## Workflow
1. **Gather every source.** Interviews, support threads, `list_feature_requests`, NPS
   (`nps-and-testimonial-collection`), sales notes (`crm_contact_timeline`), public reviews
   (`web_search`). Missing a source biases the synthesis.
2. **Capture verbatim.** Preserve the customer's actual words — they're the raw material for
   positioning and copy, and they resist your paraphrasing bias. `write_memory` (type `learning`) key quotes.
3. **Code into themes.** Tag each piece of feedback by theme (a need, a friction, a delight). Let
   themes emerge from the data rather than forcing a predetermined list.
4. **Weight honestly.** A theme's importance = frequency × intensity × requester value. Ten passing
   mentions may matter less than three from churning high-value accounts — weight, don't just count.
5. **Separate what they say from what they need.** Customers describe solutions; synthesize the
   underlying need (`jobs-to-be-done-analysis`). The need is the durable insight.
6. **Report and route.** `create_report` (kind `research_report`) with the top weighted needs and
   evidence; route to `feature-prioritization`, `positioning-and-messaging`, and roadmap.

## Decision framework — weighted themes over vocal minorities
Decide on themes weighted by frequency, intensity, and value — not on whoever emailed most recently
or loudest. Synthesis exists precisely to counter recency and volume bias.

## Definition of done
- All feedback sources gathered; verbatim captured; coded into emergent, weighted themes.
- Needs distinguished from requested solutions; top needs reported with evidence and routed.

## Common failure modes
- **Loudest-voice bias.** Weighting by volume over-serves vocal minorities.
- **Source gaps.** Missing reviews or support skews the picture.
- **Surface requests.** Synthesizing the stated ask, not the underlying need.
