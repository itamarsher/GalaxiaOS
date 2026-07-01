---
name: external-communication-review
title: External Communication Review
description: Review outbound messages before they leave so the fleet never sends something false, harmful, or off-mission.
roles: governance, ceo
---
# External Communication Review

Every outbound message the fleet sends is indexed at the tool chokepoint and can require sign-off. This
playbook reviews external comms — email, posts, published pages, ads — so nothing false, harmful, or
off-brand goes out under the company's name.

## Workflow
1. **Know it's external.** Anything reaching people outside the company (`send_email`, `publish_content`,
   `schedule_social_post`, `run_ad_campaign`) is external and reviewable. When the governance policy requires
   it, the message lands in the founder's decision inbox before sending — respect that gate.
2. **Check truthfulness.** Every claim must be true and substantiated. No invented metrics, fake
   testimonials, or capabilities we don't have. A single false public claim is a legal and trust liability.
3. **Check compliance.** For regulated claims (health, finance, security) or personal data, `check_compliance`
   and required disclosures (ads need "#ad", emails need unsubscribe). `flag_legal_risk` on anything uncertain.
4. **Check tone and brand.** On-brand voice (`brand-identity-kit`), professional, and nothing that could
   embarrass the company or damage a relationship. Read it as the recipient (and a screenshotting critic) would.
5. **Check for sensitive disclosure.** No secrets, unreleased plans, other customers' data, or internal
   figures that shouldn't be public. Once sent, it's irreversible and may be cached forever.
6. **Approve, fix, or escalate.** Clean → allow. Fixable → return with the fix. Material/uncertain →
   `request_decision` to the founder. `write_memory` (type `learning`) recurring issues to prevent repeats.

## Decision framework — irreversible and public
Treat every external message as permanent and public. When in doubt about truth, compliance, or sensitivity,
hold and escalate — the cost of blocking a message briefly is trivial next to the cost of a harmful one going out.

## Definition of done
- Message confirmed external and passed through the gate; truthfulness, compliance, tone, and sensitivity checked.
- Clean approved / fixable returned / material escalated; recurring issues recorded.

## Common failure modes
- **Unsubstantiated claims.** Public statements the product can't back — legal and trust risk.
- **Missing disclosures.** Non-compliant ads/emails.
- **Leaking sensitive info.** Secrets or others' data sent irreversibly into the world.
