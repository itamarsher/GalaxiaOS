# Connect your AI agent (MCP)

You can register and operate a company on ABOS entirely from an AI agent that
speaks [MCP](https://modelcontextprotocol.io) — Claude Code, Cursor, or any other
MCP client — without ever touching the web UI. This is the **Founder MCP**
(`backend/app/api/founder_mcp.py`): your agent acts as the founder, creating and
steering companies and resolving the decisions that gate the work.

## The one-URL recipe

Point your agent at the deployment's discovery endpoint and tell it to *register
and start a company*:

```
GET https://<your-abos-host>/connect
```

That endpoint is **public and unauthenticated**. It returns the full bootstrap
recipe, the MCP server URL, and the live tool catalog as JSON (plus a
`paste_to_agent` block) — so an agent can learn the whole surface without reading
any source.

## The steps it describes

1. **Create an account** — `POST /auth/signup` `{"email","password"}` → returns an
   `access_token`. (Already have one? `POST /auth/login`.)
2. **Mint a founder token** — `POST /founder/connection` with header
   `Authorization: Bearer <access_token>` → returns your durable founder
   connection `token`.
3. **Add the MCP server** to your agent:
   - URL: `https://<your-abos-host>/connect/founder`
   - Header: `Authorization: Bearer <token>`
4. **Operate** — call `create_company` → `generate_org` → `launch_company`, then
   steer with `get_company_snapshot`, `list_decisions`, and
   `approve_decision` / `reject_decision`.

## Notes

- **Introspection is token-optional.** `initialize` and `tools/list` on
  `/connect/founder` work with no token, so an agent can add the server URL and
  discover the self-describing tools first. Every `tools/call` still requires a
  valid founder token — an unauthenticated call returns a JSON-RPC error that
  points back at this recipe.
- **The founder token is powerful** (full account power across your companies) and
  only mintable by the authenticated user for themselves. Every company-scoped
  tool re-checks that the token's user founds the company it touches. Rotate it by
  rotating `ABOS_FOUNDER_CONNECTION_SECRET`.
- **Storage is automatic** when the deployment has a managed default store
  configured (`ABOS_R2_*`); otherwise connect one with `connect_storage`. Either
  way a company can reach launch without a browser round-trip.

Logged-out users also see a copy-pasteable version of this recipe on the app's
landing page ("Or connect your AI agent").
