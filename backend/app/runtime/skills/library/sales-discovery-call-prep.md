---
name: sales-discovery-call-prep
title: Sales Discovery Call Prep
description: Prepare a structured discovery call that uncovers the real problem, not just a feature wishlist.
roles: growth, ceo
---
# Sales Discovery Call Prep

A good discovery call is diagnosis, not a pitch. This playbook produces the research,
questions, and success criteria so the call surfaces the buyer's real pain and its cost.

## Workflow
1. **Load context.** `crm_contact_timeline` for prior touches and `crm_find_contacts`
   for others at the same account. Read any linked deal with `crm_list_deals`.
2. **Research the account.** `web_search` for their business model, recent news, and the
   likely shape of the problem we solve. Capture facts, not guesses.
3. **Write the question set** (aim for 8–10, mostly open):
   - *Situation* — how do they handle this today?
   - *Problem* — where does it break, and how often?
   - *Impact* — what does that cost them (time, money, risk)? Get a number.
   - *Vision* — what would "solved" look like for them?
   - *Decision* — who else is involved, what's the process, what's the timeline?
4. **Set the call's success criterion** before it happens: e.g. "quantified pain + named
   next step." `write_memory` (type `experiment`) the criterion.
5. **Schedule.** `create_calendar_event` with an agenda in the invite; `schedule_followup`
   for the same day to log notes.

## Talk-time heuristic
The buyer should talk ~70% of the time. If your question set can't sustain that, it's a
pitch in disguise — cut claims, add questions.

## Definition of done
- Question set written, mapped to Situation→Problem→Impact→Vision→Decision.
- Quantified-impact question included (a discovery with no cost-of-pain is incomplete).
- Success criterion recorded; call scheduled with an agenda.

## Common failure modes
- **Leading with the demo.** You can't tailor a demo you haven't earned the context for.
- **No impact number.** "It's annoying" doesn't build a business case; "it costs 6 hrs/week" does.
- **Forgetting the buying committee.** Ask who else decides on the first call, not the third.
