---
name: product-launch-gtm
title: Product Launch Go-To-Market
description: Coordinate a cross-functional product launch so positioning, assets, and channels land together.
roles: growth, ceo, product
---
# Product Launch Go-To-Market

A launch is a coordination problem: message, assets, and channels must land on the same day
pointed at the same audience. This playbook orchestrates it end to end.

## Workflow
1. **Lock positioning first.** Confirm the one-sentence value prop and target segment (from
   `positioning-and-messaging`). Everything downstream inherits this — don't start assets without it.
2. **Set the goal and date.** Define what a successful launch looks like (signups, demos,
   press) and the date. `write_memory` (type `experiment`) the target.
3. **Plan backwards from the date.** List workstreams — messaging, web/landing, content,
   social, email, sales enablement, PR — and `dispatch_tasks` to the owning roles with due dates.
4. **Prepare the channels:** landing page (`landing-page-optimization`), announcement content
   (`blog-post-production`), social sequence (`social-media-campaign`), launch email, and a
   sales one-pager (`draft_document`).
5. **Coordinate the moment.** Use a `start_chat_channel` warroom; confirm every workstream is
   green before go. `schedule_social_post` and email for the launch window.
6. **Measure the first 72 hours.** `record_metric` hourly/daily against target; `report_result`
   to the CEO with what landed and the follow-up plan.

## Decision framework — launch or slip
Slip the date if positioning isn't locked or a core asset is missing. A muddled launch can't
be re-launched; a delayed one can.

## Definition of done
- Positioning locked, all workstreams assigned with dates, warroom coordinated.
- First-72-hour results measured and reported.

## Common failure modes
- **Assets before positioning.** Everything has to be redone when the message changes.
- **No single date/goal.** Workstreams drift and land scattered.
- **Launch-and-vanish.** The 72-hour follow-up is where deals actually convert.
