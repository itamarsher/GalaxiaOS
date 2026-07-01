---
name: data-privacy-and-sharing-policy
title: Data Privacy & Sharing Policy
description: Govern what data the fleet collects, stores, and shares so user trust and privacy obligations are protected.
roles: governance, data
---
# Data Privacy & Sharing Policy

User data is a trust the company holds, not an asset to exploit. This playbook governs what data is
collected, how it's stored, and what may be shared — protecting users and meeting privacy obligations.

## Workflow
1. **Know what data exists.** Inventory what the fleet collects and stores (`list_data_policies`,
   `list_company_files`). You can't govern data you haven't mapped; unknown data stores are unmanaged risk.
2. **Apply data minimization.** Collect and keep only what's needed for a real purpose. Data you don't hold
   can't leak — the safest data is uncollected. Challenge collection that lacks a clear use.
3. **Classify by sensitivity.** Personal, financial, and confidential data need stronger controls than
   public data. Classification drives who can access it and whether it can leave the company.
4. **Govern sharing tightly.** Before any data leaves the company (integrations, analytics, third parties),
   check it's permitted and safe. Use `set_external_sharing_policy` to control it; `check_compliance` /
   `flag_legal_risk` on anything involving personal data. Default to not sharing.
5. **Respect user rights.** Ensure the company can honor access, correction, and deletion requests, and that
   consent is real and revocable. `request_user_action` for founder input on policy-level decisions.
6. **Document and enforce.** `update_company_playbook` with the policy; `write_memory` (type `learning`) any
   incident or gap; the policy must be enforced at the tool chokepoint, not just written down.

## Decision framework — minimize and default-closed
Collect the minimum, classify honestly, and default to NOT sharing unless there's a clear, permitted, safe
reason. Privacy protects the trust the whole business depends on; treat a shortcut here as a potential breach.

## Definition of done
- Data inventoried and classified; minimization applied; sharing governed default-closed with checks.
- User rights honorable; policy documented in the playbook and enforced at the chokepoint.

## Common failure modes
- **Unmapped data.** Ungoverned stores you didn't know you had.
- **Over-collection.** Holding data with no purpose multiplies breach impact.
- **Default-open sharing.** Letting data leave without a permitted, safe reason.
