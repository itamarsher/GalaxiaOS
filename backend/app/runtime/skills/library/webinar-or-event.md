---
name: webinar-or-event
title: Webinar or Event
description: Plan and run a webinar/event that generates qualified pipeline, not just registrations.
roles: growth
---
# Webinar or Event

Registrations are vanity; pipeline is the point. This playbook runs a webinar or event
designed to attract and convert the right audience, then work the leads afterward.

## Workflow
1. **Pick a topic the ICP needs**, not one that flatters the product. `web_search` and
   `list_feature_requests` for real questions. The topic is the whole draw.
2. **Set the pipeline goal.** Target = qualified leads / meetings booked, not sign-ups.
   `write_memory` (type `experiment`) the target.
3. **Promote.** Landing/registration page, `schedule_social_post`, and `send_email` to relevant
   segments. Sequence reminders (registrants forget) via `schedule_followup`.
4. **Prepare the content** to teach first and pitch lightly at the end. `draft_document` for the
   script; `generate_image`/`generate_video` for assets. Rehearse the demo (`sales-demo-script`).
5. **Run it, then work the leads FAST.** The 24–48h after is where pipeline is won. `log_lead`
   attendees, score them (`inbound-lead-qualification`), and `schedule_followup` per interest level.
6. **Measure the funnel.** `record_metric` for registered → attended → qualified → booked.
   `write_memory` (type `learning`) which topic/format drove real pipeline.

## Decision framework — worth repeating?
Judge by qualified meetings per hour invested, not attendance. A 20-person webinar that books
5 meetings beats a 200-person one that books zero.

## Definition of done
- ICP-relevant topic, pipeline (not signup) goal, fast post-event follow-up.
- Full funnel measured; repeat decision based on qualified meetings.

## Common failure modes
- **Optimizing registrations.** Big lists, no pipeline is a common, expensive trap.
- **Slow follow-up.** Interest decays in days; work leads immediately.
- **Pitch-heavy content.** Teach first or the audience tunes out.
