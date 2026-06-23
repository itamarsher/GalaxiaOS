"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, type ApiKey, type Company, type McpServer } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

// The two keys ABOS understands today: the BYOK LLM provider key (required to
// run) and an optional GitHub token (lets the platform agent file real issues).
const SLOTS: { provider: string; label: string; hint: string; placeholder: string }[] = [
  {
    provider: "anthropic",
    label: "Anthropic API key",
    hint: "Required. The BYOK key your agents use to think. Encrypted at rest; only a fingerprint is shown.",
    placeholder: "sk-ant-…",
  },
  {
    provider: "github",
    label: "GitHub token",
    hint: "Optional. Lets the platform agent open real issues for bug reports and capability requests. Without it, issues go to an offline tracker.",
    placeholder: "ghp_…",
  },
  {
    provider: "tavily",
    label: "Tavily API key",
    hint: "Optional. Enables real web search for your agents. Without it, web search returns simulated (placeholder) results.",
    placeholder: "tvly-…",
  },
  {
    provider: "resend",
    label: "Resend API key",
    hint: "Optional. Lets agents send real email from your own domain via Resend (generous free tier: 3,000/mo). With a key set, Resend becomes the email provider; without it, email is simulated.",
    placeholder: "re_…",
  },
];

export default function SettingsPage() {
  const { id } = useParams<{ id: string }>();
  const keys = usePoll(() => api.apiKeys(id), 0, [id]);
  const company = usePoll(() => api.company(id), 0, [id]);
  const list = keys.data ?? [];

  return (
    <div>
      <h2>Settings</h2>
      <p className="muted">Manage the API keys this company uses. Plaintext is never stored or shown — only a fingerprint.</p>

      <FromAddress companyId={id} current={company.data ?? null} onChange={() => company.reload()} />

      {SLOTS.map((slot) => (
        <KeySlot
          key={slot.provider}
          companyId={id}
          slot={slot}
          current={list.find((k) => k.provider === slot.provider) ?? null}
          onChange={() => keys.reload()}
        />
      ))}

      <CloudflareCard companyId={id} />
      <GoogleDriveCard companyId={id} />
      <McpServersCard companyId={id} />

      {/* Any other stored keys (e.g. a provider added directly via the API).
          "cloudflare" and "google_drive" are managed by their own cards above. */}
      {list
        .filter(
          (k) =>
            !SLOTS.some((s) => s.provider === k.provider) &&
            k.provider !== "cloudflare" &&
            k.provider !== "google_drive",
        )
        .map((k) => (
          <OtherKey key={k.id} companyId={id} apiKey={k} onChange={() => keys.reload()} />
        ))}
    </div>
  );
}

// Cloudflare powers landing-page hosting (Pages) and connecting a bought domain
// (DNS). It needs an API token (secret, encrypted at rest) plus the account id.
function CloudflareCard({ companyId }: { companyId: string }) {
  const status = usePoll(() => api.cloudflareStatus(companyId), 0, [companyId]);
  const configured = status.data?.configured ?? false;
  const [token, setToken] = useState("");
  const [account, setAccount] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    if (token.trim().length < 8 || account.trim().length < 8) {
      setErr("Enter both the API token and the account id."); return;
    }
    setBusy(true); setErr(null);
    try {
      await api.setCloudflare(companyId, token.trim(), account.trim());
      setToken(""); setAccount("");
      status.reload();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Remove Cloudflare credentials? Landing-page hosting and domain connection will stop working.")) return;
    setBusy(true); setErr(null);
    try { await api.clearCloudflare(companyId); status.reload(); }
    catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="card">
      <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>Cloudflare (websites &amp; domains)</span>
        {configured ? <span className="status active">Configured</span> : <span className="status pending">Not set</span>}
      </div>
      <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
        Lets agents publish landing pages and connect bought domains. Create an API token with
        Pages:Edit, DNS:Edit and Zone:Edit. The token is encrypted at rest; only the account id is shown back.
      </p>

      {configured && status.data?.account_id && (
        <div className="kv" style={{ marginTop: 10 }}>
          <span>Account id</span>
          <span><code>{status.data.account_id}</code></span>
        </div>
      )}

      <label>{configured ? "Replace API token" : "API token"}</label>
      <input type="password" value={token} placeholder="cfat_…"
        onChange={(e) => setToken(e.target.value)} />
      <label>Account id</label>
      <input type="text" value={account} placeholder="d543238dffd9…"
        onChange={(e) => setAccount(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && save()} />
      <div className="btnrow">
        <button disabled={busy || !token.trim() || !account.trim()} onClick={save}>
          {configured ? "Update" : "Save"}
        </button>
        {configured && <button className="ghost danger" disabled={busy} onClick={remove}>Remove</button>}
      </div>
      {err && <div className="err">{err}</div>}
    </div>
  );
}

// Google Drive is the company's file store: agents file deliverables, financial
// records, data-room docs, brand guidelines and received files into the founder's
// own Drive under .abos/<company>/…. One-click connect: the button sends the
// founder to Google's consent screen; the callback stores a refresh token. No
// Cloud Console setup — the deployment owns the OAuth app.
function GoogleDriveCard({ companyId }: { companyId: string }) {
  const status = usePoll(() => api.googleDriveStatus(companyId), 0, [companyId]);
  const configured = status.data?.configured ?? false;
  const canConnect = status.data?.connect_available ?? false;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Outcome of the OAuth round-trip, surfaced via ?gdrive=… on return. Read from
  // the URL on the client (avoids a useSearchParams suspense boundary).
  const [outcome, setOutcome] = useState<string | null>(null);
  useEffect(() => {
    setOutcome(new URLSearchParams(window.location.search).get("gdrive"));
  }, []);

  const connect = async () => {
    setBusy(true); setErr(null);
    try {
      const { authorize_url } = await api.googleDriveConnect(companyId);
      window.location.href = authorize_url; // hand off to Google's consent screen
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Disconnect Google Drive? Agents will stop filing documents to your Drive.")) return;
    setBusy(true); setErr(null);
    try { await api.clearGoogleDrive(companyId); status.reload(); }
    catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="card">
      <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>Google Drive (file store)</span>
        {configured ? <span className="status active">Connected</span> : <span className="status pending">Not set</span>}
      </div>
      <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
        Your agents file every deliverable, financial record, data-room document, brand
        guideline and received file into your own Drive under <code>.abos/&lt;company&gt;/…</code> —
        ready for audits and due diligence. Connect with one click; ABOS only ever touches
        the files it creates.
      </p>

      {configured && status.data?.root_folder_id && (
        <div className="kv" style={{ marginTop: 10 }}>
          <span>Root folder</span>
          <span><code>{status.data.root_folder_id}</code></span>
        </div>
      )}

      {outcome === "connected" && !configured && (
        <div className="muted" style={{ fontSize: 13, marginTop: 10 }}>Connecting…</div>
      )}
      {outcome && outcome !== "connected" && (
        <div className="err">
          {outcome === "denied"
            ? "Authorization was cancelled."
            : "Couldn't connect Google Drive. Please try again."}
        </div>
      )}

      {!canConnect && !configured ? (
        <p className="muted" style={{ fontSize: 13, marginTop: 10 }}>
          Google Drive connect isn&apos;t enabled on this deployment.
        </p>
      ) : (
        <div className="btnrow">
          <button disabled={busy} onClick={connect}>
            {busy ? "Redirecting…" : configured ? "Reconnect with Google" : "Connect with Google"}
          </button>
          {configured && <button className="ghost danger" disabled={busy} onClick={remove}>Disconnect</button>}
        </div>
      )}
      {err && <div className="err">{err}</div>}
    </div>
  );
}

function McpServersCard({ companyId }: { companyId: string }) {
  const servers = usePoll(() => api.mcpServers(companyId), 0, [companyId]);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [auth, setAuth] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const list = servers.data ?? [];

  const add = async () => {
    if (name.trim().length < 1 || url.trim().length < 4) {
      setErr("Enter a name and a server URL."); return;
    }
    setBusy(true); setErr(null);
    try {
      await api.addMcpServer(companyId, {
        name: name.trim(),
        url: url.trim(),
        auth_token: auth.trim() || undefined,
      });
      setName(""); setUrl(""); setAuth("");
      servers.reload();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const refresh = async (s: McpServer) => {
    setBusy(true); setErr(null);
    try { await api.refreshMcpServer(companyId, s.id); servers.reload(); }
    catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
    finally { setBusy(false); }
  };

  const remove = async (s: McpServer) => {
    if (!window.confirm(`Disconnect "${s.label}"? Agents will lose its ${s.tool_count} tool(s).`)) return;
    setBusy(true); setErr(null);
    try { await api.deleteMcpServer(companyId, s.id); servers.reload(); }
    catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="card">
      <div className="step">Connected tools (MCP servers)</div>
      <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
        Connect your own MCP servers (CRM, analytics, internal APIs) to give agents real tools.
        The optional bearer token is encrypted at rest. Tools are governed like any external action.
      </p>

      {list.map((s) => (
        <div key={s.id} className="kv" style={{ marginTop: 10, alignItems: "flex-start" }}>
          <span>
            <code>{s.name}</code>
            <span className="muted" style={{ fontSize: 12, display: "block" }}>{s.url}</span>
            {s.last_error
              ? <span className="err" style={{ fontSize: 12 }}>{s.last_error}</span>
              : <span className="muted" style={{ fontSize: 12 }}>{s.tool_count} tool(s){s.tools.length ? `: ${s.tools.join(", ")}` : ""}</span>}
          </span>
          <span style={{ display: "flex", gap: 6 }}>
            <button className="ghost" style={{ marginTop: 0 }} disabled={busy} onClick={() => refresh(s)}>Refresh</button>
            <button className="ghost danger" style={{ marginTop: 0 }} disabled={busy} onClick={() => remove(s)}>Remove</button>
          </span>
        </div>
      ))}

      <label>Name</label>
      <input value={name} placeholder="acme-crm" onChange={(e) => setName(e.target.value)} />
      <label>Server URL</label>
      <input value={url} placeholder="https://mcp.example.com/mcp" onChange={(e) => setUrl(e.target.value)} />
      <label>Bearer token (optional)</label>
      <input type="password" value={auth} placeholder="token…"
        onChange={(e) => setAuth(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && add()} />
      <div className="btnrow">
        <button disabled={busy || !name.trim() || !url.trim()} onClick={add}>
          {busy ? "Connecting…" : "Connect"}
        </button>
      </div>
      {err && <div className="err">{err}</div>}
    </div>
  );
}

function FromAddress({
  companyId,
  current,
  onChange,
}: {
  companyId: string;
  current: Company | null;
  onChange: () => void;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Seed the input from the saved value once it loads.
  useEffect(() => {
    setValue(current?.email_from ?? "");
  }, [current?.email_from]);

  const save = async () => {
    const v = value.trim();
    if (v && !v.includes("@")) { setErr("Enter an email address, e.g. hello@acme.com."); return; }
    setBusy(true); setErr(null); setSaved(false);
    try {
      await api.updateCompany(companyId, { email_from: v });
      setSaved(true);
      onChange();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>Sender (&ldquo;From:&rdquo;) address</span>
        {current?.email_from
          ? <span className="status active">Set</span>
          : <span className="status pending">Using default</span>}
      </div>
      <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
        The address your agents send email as. With a Resend key, this must be on a domain
        you&apos;ve verified in your Resend account (add its SPF/DKIM DNS records first). Accepts
        a plain address or a display name, e.g. <code>hello@acme.com</code> or <code>Acme &lt;hello@acme.com&gt;</code>.
        Leave blank to use the deployment default.
      </p>
      <label>From address</label>
      <input
        value={value}
        placeholder="hello@yourstartup.com"
        onChange={(e) => { setValue(e.target.value); setSaved(false); }}
        onKeyDown={(e) => e.key === "Enter" && save()}
      />
      <div className="btnrow">
        <button disabled={busy || value.trim() === (current?.email_from ?? "")} onClick={save}>Save</button>
      </div>
      {saved && <div className="muted" style={{ fontSize: 13 }}>Saved.</div>}
      {err && <div className="err">{err}</div>}
    </div>
  );
}

function KeySlot({
  companyId,
  slot,
  current,
  onChange,
}: {
  companyId: string;
  slot: { provider: string; label: string; hint: string; placeholder: string };
  current: ApiKey | null;
  onChange: () => void;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    const v = value.trim();
    if (v.length < 8) { setErr("That key looks too short."); return; }
    setBusy(true); setErr(null);
    try {
      await api.addApiKey(companyId, v, slot.provider);
      setValue("");
      onChange();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!current) return;
    if (!window.confirm(`Remove the ${slot.label}? Agents relying on it will stop working until you set a new one.`)) return;
    setBusy(true); setErr(null);
    try {
      await api.deleteApiKey(companyId, current.id);
      onChange();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>{slot.label}</span>
        {current
          ? <span className="status active">Configured</span>
          : <span className="status pending">Not set</span>}
      </div>
      <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>{slot.hint}</p>

      {current && (
        <div className="kv" style={{ marginTop: 10 }}>
          <span>Current key</span>
          <span><code>{current.key_fingerprint}</code></span>
        </div>
      )}

      <label>{current ? "Replace with a new key" : "Set key"}</label>
      <input
        type="password"
        value={value}
        placeholder={slot.placeholder}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && save()}
      />
      <div className="btnrow">
        <button disabled={busy || !value.trim()} onClick={save}>{current ? "Update" : "Save"}</button>
        {current && <button className="ghost danger" disabled={busy} onClick={remove}>Remove</button>}
      </div>
      {err && <div className="err">{err}</div>}
    </div>
  );
}

function OtherKey({ companyId, apiKey, onChange }: { companyId: string; apiKey: ApiKey; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const remove = async () => {
    if (!window.confirm(`Remove the ${apiKey.provider} key?`)) return;
    setBusy(true);
    try { await api.deleteApiKey(companyId, apiKey.id); onChange(); } finally { setBusy(false); }
  };
  return (
    <div className="card">
      <div className="step">{apiKey.provider}</div>
      <div className="kv" style={{ marginTop: 10 }}>
        <span><code>{apiKey.key_fingerprint}</code></span>
        <button className="ghost danger" style={{ marginTop: 0 }} disabled={busy} onClick={remove}>Remove</button>
      </div>
    </div>
  );
}
