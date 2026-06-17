"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { api, type ApiKey } from "@/lib/api";
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
];

export default function SettingsPage() {
  const { id } = useParams<{ id: string }>();
  const keys = usePoll(() => api.apiKeys(id), 0, [id]);
  const list = keys.data ?? [];

  return (
    <div>
      <h2>Settings</h2>
      <p className="muted">Manage the API keys this company uses. Plaintext is never stored or shown — only a fingerprint.</p>

      {SLOTS.map((slot) => (
        <KeySlot
          key={slot.provider}
          companyId={id}
          slot={slot}
          current={list.find((k) => k.provider === slot.provider) ?? null}
          onChange={() => keys.reload()}
        />
      ))}

      {/* Any other stored keys (e.g. a provider added directly via the API). */}
      {list.filter((k) => !SLOTS.some((s) => s.provider === k.provider)).map((k) => (
        <OtherKey key={k.id} companyId={id} apiKey={k} onChange={() => keys.reload()} />
      ))}
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
