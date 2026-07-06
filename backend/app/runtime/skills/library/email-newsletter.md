---
name: email-newsletter
title: Email Newsletter
description: Run a recurring newsletter that earns opens by being useful, and respects consent and deliverability.
roles: growth
---
# Email Newsletter

A newsletter is a standing relationship with people who opted in. This playbook keeps it
useful, consistent, and compliant so it stays an asset, not a spam complaint.

## Workflow
1. **Confirm consent.** Only send to contacts who opted in (`crm_find_contacts`). Sending to
   scraped or unconsented lists risks deliverability and law — if unsure, `check_compliance`.
2. **Pick one job per issue.** Educate, announce, or activate — not all three. A newsletter
   that tries to do everything gets deleted.
3. **Lead with value.** The subscriber's takeaway comes before any ask. Curate real insight,
   not a list of company updates.
4. **Draft and personalize.** `draft_document` in company voice; segment if the list warrants
   different messages. Keep it skimmable.
5. **Send and respect exits.** `send_email` to the segment; honor unsubscribes immediately —
   an easy exit protects deliverability and trust.
6. **Measure the right things.** `record_metric` for open, click, and unsubscribe rate.
   Rising unsubscribes = you're extracting more than you give; recalibrate.

## Decision framework — send or hold
If you don't have something genuinely useful this issue, skip it. Cadence matters, but
sending filler to hit a schedule trains people to ignore or leave.

## Definition of done
- Consented list only; one clear job; value before ask; unsubscribe honored.
- Open/click/unsubscribe recorded and reviewed.

## Common failure modes
- **Unconsented sends.** Legal and deliverability risk; check when unsure.
- **All-about-us content.** Subscribers reward usefulness, not press releases.
- **Filler to hit cadence.** Rising unsubscribes is the tell.
