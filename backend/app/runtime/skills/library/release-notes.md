---
name: release-notes
title: Release Notes
description: Write release notes that tell users what changed, why it helps them, and what to do next.
roles: product, growth
---
# Release Notes

Release notes are a small, recurring touchpoint that either builds momentum or gets ignored.
This playbook writes ones users actually read — framed around their benefit, not your changelog.

## Workflow
1. **Gather what shipped.** From the sprint/PRDs and `list_repo_files` / issue history. Separate
   user-facing changes from internal ones — users care about the former.
2. **Lead with benefit.** For each item: what changed → why it helps you → how to use it. "You
   can now export to CSV so your data lives in your own tools" beats "Added CSV export."
3. **Group and prioritize.** Headline the one or two changes that matter most; list smaller fixes
   below. Don't bury the lede in a flat list.
4. **Be honest about breaking changes.** Call out anything that changes existing behavior, with
   migration guidance. Hiding breakage destroys trust faster than the change itself.
5. **Draft in company voice.** `draft_document` (pull voice from `get_company_playbook`); add a
   visual with `generate_image` if it clarifies a new flow.
6. **Publish and distribute.** `publish_content`; notify relevant users (`send_email` /
   `send_notification`); loop back to requesters whose asks shipped (`feature-request-triage`).

## Decision framework — include or omit
Include a change if a user's behavior could change because of it. Omit pure internals. When in
doubt about a breaking change, over-communicate.

## Definition of done
- User-facing changes framed by benefit; top items headlined; breaking changes flagged with guidance.
- Published, distributed, and looped back to requesters.

## Common failure modes
- **Changelog dump.** "Fixed bugs, improved performance" tells users nothing.
- **Hidden breakage.** Undisclosed behavior changes erode trust.
- **Feature-first framing.** Users care about their outcome, not your implementation.
