---
name: plaid
title: Plaid
description: Link a bank account, or pull balances, auth, or transactions via Plaid — bank connectivity, tokens, and webhooks.
roles: finance, platform
---
# Plaid

Plaid is the fleet's bank-connectivity layer — link accounts and read balance, auth, and transactions
through one API. The ABOS-adapted rule: **connect it as a tool first, never assume it's wired**, and
because Plaid handles bank credentials and financial data, **sandbox first, least-privilege always, and
never expose a token**.

## Connect before you link
1. **Find the tool.** `discover_tools` with query `plaid`; it exposes as `mcp__plaid__*` once the founder
   connects it. Load what you need with `use_tool` (create link token, exchange, read accounts).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Plaid in
   Settings (client ID + secret, environment). Never invent a linked account, balance, or transaction — a
   phantom balance is worse than none. If the capability can't exist yet, `request_capability`.
3. **Screen the egress.** Linking sends bank data to a third party; `check_compliance` /
   `list_data_policies` before any sensitive financial data flows out.

## Integrate the way pros do
4. **Sandbox before production.** Build and test in Plaid's sandbox — simulate logins, transaction volume,
   and specific error codes — before touching a real institution. Keep sandbox and production keys separate.
5. **Least-privilege products.** Request only the products you need (Balance, Auth, Transactions), not the
   full set — narrower scope is more secure and earns user trust. The `public_token`/`link_token` are the
   only tokens that touch the client; exchange them for the `access_token` on the backend only.
6. **Guard the access token.** Access tokens are long-lived — store them encrypted server-side, keep them
   out of logs, never in client code, and rotate secrets. Always HTTPS, always the official SDK.
7. **Webhook-driven, verified.** Process `TRANSACTIONS`/`ITEM` webhooks in background workers, not the
   user path, and verify webhook signatures so a spoofed event can't drive a false read.

## Mirror it in ABOS and file it
8. **Record what you read.** `read_financials` and `record_transaction` mirror real Plaid data into the
   ledger — never fabricate figures; if a link is broken (ITEM_LOGIN_REQUIRED), `request_user_action` to
   re-auth, don't guess the balance.
9. **File and hand off.** `save_file` exported statements/reconciliations (category `financial`) with
   context; `write_memory` (type `result`), `dispatch_task` platform for build work, `report_result`.

## Definition of done
- Plaid confirmed connected (or escalated, never faked); data-egress screened.
- Sandbox-tested, least-privilege products, access token backend-only and encrypted, webhooks verified.
- Real data mirrored via `read_financials`/`record_transaction`, artifacts `save_file`d (financial).

## Common failure modes
- **Phantom balance.** Reporting a balance or transaction Plaid was never connected to return — escalate.
- **Leaked access token.** Token in client code, logs, or unencrypted storage — a direct bank-data breach.
- **Unverified webhook.** Acting on an unsigned event, letting a spoofed payload drive a false read.
