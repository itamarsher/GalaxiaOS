"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  api,
  fmtUsd,
  type ApiKey,
  type Company,
  type DelegateSettings,
  type DelegateWebhook,
  type ManagedStatus,
  type McpServer,
  type WebhookEvents,
} from "@/lib/api";
import { usePoll } from "@/lib/useApi";
import { CloudflareCard, GoogleDriveCard, UserGoogleDriveCard } from "@/lib/connectors";

// The keys GalaxiaOS understands today. The BYOK LLM provider key is required to
// run; the rest are optional integrations. (GitHub issue filing is handled centrally
// by the deployment's own token, so there's no per-company GitHub key here.)
//
// The LLM provider is chosen by whichever LLM key you set — Anthropic (Claude) or
// one of the open-source hosts below. Set exactly one: adding a new LLM key
// switches your whole fleet to that provider. Open-source hosts serve models like
// Llama 3.3, DeepSeek R1, Qwen, and gpt-oss — typically far cheaper per token than
// Claude, with no infrastructure to run.
const SLOTS: { provider: string; label: string; hint: string; placeholder: string }[] = [
  {
    provider: "anthropic",
    label: "Anthropic API key",
    hint: "The BYOK key your agents use to think (Claude). Encrypted at rest; only a fingerprint is shown. Set one LLM key — this or an open-source host below.",
    placeholder: "sk-ant-…",
  },
  {
    provider: "openrouter",
    label: "OpenRouter API key (open-source models)",
    hint: "Open-source alternative to Claude. One key routes to 300+ models (Llama 3.3, DeepSeek R1, Qwen, gpt-oss) — usually far cheaper per token. Setting this switches your fleet to open-source models.",
    placeholder: "sk-or-…",
  },
  {
    provider: "groq",
    label: "Groq API key (open-source models)",
    hint: "Open-source alternative to Claude, optimized for very low latency (Llama 3.3, gpt-oss, DeepSeek distills). Setting this switches your fleet to open-source models.",
    placeholder: "gsk_…",
  },
  {
    provider: "together",
    label: "Together AI API key (open-source models)",
    hint: "Open-source alternative to Claude with a broad model catalog (Llama, DeepSeek, Qwen). Setting this switches your fleet to open-source models.",
    placeholder: "…",
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

      <ManagedCard companyId={id} />

      <DelegateCard companyId={id} />

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
      {/* Account-wide Drive (per user) is the default going forward: connect once,
          and every business files into your Drive. The per-company card below stays
          for a Drive linked to just this one company (it takes precedence when set). */}
      <UserGoogleDriveCard />
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

// Managed tier: the founder's platform-funded standing. Only rendered when the
// deployment has managed mode on; otherwise it's a pure-BYOK deployment and this
// card stays hidden. Shows the free-tier meter and (when a BYO key is present)
// notes that the fleet runs on the founder's own account instead.
function ManagedCard({ companyId }: { companyId: string }) {
  const status = usePoll(() => api.managedStatus(companyId), 0, [companyId]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const s: ManagedStatus | null = status.data ?? null;

  if (!s || !s.managed_mode) return null; // BYOK-only deployment → nothing to show

  const upgrade = async () => {
    setBusy(true); setErr(null);
    try {
      const { url } = await api.upgradeManaged(companyId);
      window.location.href = url;
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
      setBusy(false);
    }
  };

  const usedPct = s.free_allowance_cents > 0
    ? Math.min(100, Math.round((s.platform_spent_cents / s.free_allowance_cents) * 100))
    : 0;

  return (
    <div className="card">
      <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>Managed plan</span>
        <span className={`status ${s.tier === "paid_managed" ? "active" : s.allowed ? "active" : "pending"}`}>
          {s.tier === "paid_managed" ? "Managed (paid)" : s.tier === "blocked" ? "Free — used up" : "Free tier"}
        </span>
      </div>

      {s.has_own_llm_key ? (
        <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
          You&apos;re running on your own model key ({s.byo_llm_providers.join(", ")}) — no platform cap
          applies. The managed tier is a fallback if you remove your key.
        </p>
      ) : s.tier === "paid_managed" ? (
        <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
          Metered managed usage — the platform runs your fleet and bills usage to your card. Add
          your own model key anytime to switch back to bring-your-own.
        </p>
      ) : (
        <>
          <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
            The platform funds your fleet up to {fmtUsd(s.free_allowance_cents)} of usage — no keys
            needed. Used {fmtUsd(s.platform_spent_cents)} ({fmtUsd(s.free_remaining_cents)} left).
          </p>
          <div className="bar" style={{ marginTop: 8 }}><span style={{ width: `${usedPct}%` }} /></div>
          {!s.allowed && s.reason && <p className="err" style={{ fontSize: 13 }}>{s.reason}</p>}
          <div className="btnrow">
            {s.upgrade_available ? (
              <button disabled={busy} onClick={upgrade}>
                {busy ? "Redirecting…" : "Upgrade to managed (pay as you go)"}
              </button>
            ) : (
              <span className="muted" style={{ fontSize: 12 }}>
                Add your own model key below to keep going without limits.
              </span>
            )}
          </div>
        </>
      )}
      {err && <div className="err">{err}</div>}
    </div>
  );
}

// The four-stop autonomy slider + notification webhooks. Slider and webhooks share
// one config row, so every save PUTs the whole thing (autonomy level + webhooks).
const AUTONOMY = [
  { level: 1, name: "Manual", blurb: "Every decision comes to you. Nothing is auto-approved — the strictest setting." },
  { level: 2, name: "Assisted", blurb: "Claude handles plan approvals and low-stakes confirmations for you. All spending, hires, and outbound messages still escalate." },
  { level: 3, name: "Supervised", blurb: "Adds minor expenditures (up to $50 each) and more autonomy. Larger spend, hires, and external messages still come to you." },
  { level: 4, name: "Autonomous", blurb: "Fully autonomous within budget — Claude resolves everything, escalating only extreme cases (very large spend).", warn: "Set a firm budget and load-balance your agents responsibly — at this level Claude can spend and act without asking." },
] as const;

const EVENT_LABELS: { value: WebhookEvents; label: string }[] = [
  { value: "all", label: "Everything" },
  { value: "escalations", label: "Only what needs me" },
  { value: "auto_handled", label: "Only what Claude handled" },
];

function DelegateCard({ companyId }: { companyId: string }) {
  const cfg = usePoll(() => api.delegate(companyId), 0, [companyId]);
  const [level, setLevel] = useState(1);
  const [hooks, setHooks] = useState<DelegateWebhook[]>([]);
  const [secret, setSecret] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Seed local state once the config loads.
  useEffect(() => {
    if (!cfg.data) return;
    setLevel(cfg.data.autonomy_level);
    setHooks(cfg.data.webhooks);
    setSecret(cfg.data.signing_secret);
  }, [cfg.data]);

  const save = async (patch: { autonomy_level: number; webhooks: DelegateWebhook[]; rotate_secret?: boolean; telegram_events?: WebhookEvents }) => {
    setBusy(true); setErr(null); setSaved(false);
    try {
      const next: DelegateSettings = await api.updateDelegate(companyId, patch);
      setLevel(next.autonomy_level);
      setHooks(next.webhooks);
      setSecret(next.signing_secret);
      setSaved(true);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const pick = AUTONOMY[level - 1];
  const validHooks = hooks.filter((h) => /^https?:\/\//.test(h.url.trim()));

  return (
    <div className="card">
      <div className="step">Autonomy &amp; notifications</div>
      <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
        How much your Claude delegate resolves on your behalf, and where it pings you when something needs you.
      </p>

      {/* Four-stop slider */}
      <label style={{ marginTop: 14 }}>Autonomy level</label>
      <input
        type="range" min={1} max={4} step={1} value={level}
        disabled={busy}
        onChange={(e) => { const v = Number(e.target.value); setLevel(v); save({ autonomy_level: v, webhooks: hooks }); }}
        style={{ width: "100%" }}
      />
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }} className="muted">
        {AUTONOMY.map((a) => (
          <span key={a.level} style={{ fontWeight: a.level === level ? 700 : 400, color: a.level === level ? "inherit" : undefined }}>
            {a.name}
          </span>
        ))}
      </div>
      <p style={{ fontSize: 13, marginTop: 10 }}>
        <strong>{pick.name}.</strong> {pick.blurb}
      </p>
      {"warn" in pick && pick.warn && (
        <p className="err" style={{ fontSize: 13, marginTop: 6 }}>⚠️ {pick.warn}</p>
      )}

      {/* Notification webhooks (up to 3) */}
      <div className="step" style={{ marginTop: 18 }}>Notification webhooks</div>
      <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
        Up to 3 URLs (Slack/Telegram/your phone) to POST decisions to. Every request is HMAC-signed with your
        signing secret so the receiver can verify it&apos;s really from us.
      </p>

      {hooks.map((h, i) => (
        <div key={i} className="kv" style={{ marginTop: 10, alignItems: "center", gap: 6 }}>
          <input
            value={h.url}
            placeholder="https://hooks.slack.com/…"
            onChange={(e) => setHooks(hooks.map((x, j) => (j === i ? { ...x, url: e.target.value } : x)))}
            style={{ flex: 1 }}
          />
          <select
            value={h.events}
            onChange={(e) => setHooks(hooks.map((x, j) => (j === i ? { ...x, events: e.target.value as WebhookEvents } : x)))}
          >
            {EVENT_LABELS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <button className="ghost danger" style={{ marginTop: 0 }} onClick={() => setHooks(hooks.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      {hooks.length < 3 && (
        <button className="ghost" style={{ marginTop: 10 }}
          onClick={() => setHooks([...hooks, { url: "", events: "all" }])}>
          + Add webhook
        </button>
      )}

      {secret && (
        <div className="kv" style={{ marginTop: 12, alignItems: "flex-start" }}>
          <span>
            Signing secret
            <span className="muted" style={{ fontSize: 12, display: "block" }}>
              Verify <code>X-Abos-Signature: sha256=HMAC(secret, &quot;{"{timestamp}"}.{"{body}"}&quot;)</code> on your endpoint.
            </span>
          </span>
          <code style={{ wordBreak: "break-all" }}>{secret}</code>
        </div>
      )}

      {/* Telegram — shared platform bot; the founder just connects their chat. */}
      {cfg.data?.telegram.enabled && (
        <>
          <div className="step" style={{ marginTop: 18 }}>Telegram</div>
          {cfg.data.telegram.connected ? (
            <div className="kv" style={{ marginTop: 8, alignItems: "center", gap: 6 }}>
              <span className="status active">Connected</span>
              <select
                value={cfg.data.telegram.events}
                disabled={busy}
                onChange={async (e) => {
                  await save({ autonomy_level: level, webhooks: validHooks, telegram_events: e.target.value as WebhookEvents });
                  cfg.reload();
                }}
              >
                {EVENT_LABELS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <button className="ghost danger" style={{ marginTop: 0 }} disabled={busy}
                onClick={async () => { setBusy(true); try { await api.telegramDisconnect(companyId); cfg.reload(); } finally { setBusy(false); } }}>
                Disconnect
              </button>
            </div>
          ) : (
            <>
              <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
                Get pinged on Telegram — no bot setup needed. Tap Connect, press <strong>Start</strong> in the chat that opens, then refresh.
              </p>
              <div className="btnrow">
                <button disabled={busy}
                  onClick={async () => {
                    setBusy(true); setErr(null);
                    try {
                      const { connect_url } = await api.telegramConnectLink(companyId);
                      if (connect_url) window.open(connect_url, "_blank", "noopener");
                      else setErr("Telegram isn't configured on this deployment yet.");
                    } catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
                    finally { setBusy(false); }
                  }}>
                  Connect Telegram
                </button>
                <button className="ghost" disabled={busy} onClick={() => cfg.reload()}>Refresh</button>
              </div>
            </>
          )}
        </>
      )}

      <div className="btnrow">
        <button disabled={busy} onClick={() => save({ autonomy_level: level, webhooks: validHooks })}>
          {busy ? "Saving…" : "Save webhooks"}
        </button>
        <button className="ghost" disabled={busy}
          onClick={() => save({ autonomy_level: level, webhooks: validHooks, rotate_secret: true })}>
          {secret ? "Rotate secret" : "Generate secret"}
        </button>
      </div>
      {saved && <div className="muted" style={{ fontSize: 13 }}>Saved.</div>}
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
