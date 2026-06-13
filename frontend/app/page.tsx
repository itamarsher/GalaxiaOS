"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, fmtUsd, type Preview } from "@/lib/api";

type Step = "auth" | "mission" | "key" | "review";

export default function Home() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("auth");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mission, setMission] = useState("");
  const [budget, setBudget] = useState("500");
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);

  async function guard(fn: () => Promise<void>) {
    setErr(null); setBusy(true);
    try { await fn(); } catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
    finally { setBusy(false); }
  }

  const doAuth = (signup: boolean) =>
    guard(async () => {
      const res = signup ? await api.signup(email, password) : await api.login(email, password);
      api.setToken(res.access_token);
      setStep("mission");
    });

  const startOnboarding = () =>
    guard(async () => {
      const c = await api.startOnboarding(mission, Math.round(parseFloat(budget) * 100), []);
      setCompanyId(c.id);
      setStep("key");
    });

  const submitKeyAndGenerate = () =>
    guard(async () => {
      if (!companyId) return;
      await api.addApiKey(companyId, apiKey);
      setPreview(await api.generate(companyId));
      setStep("review");
    });

  const launch = () =>
    guard(async () => {
      if (!companyId) return;
      await api.launch(companyId);
      router.push(`/c/${companyId}`);
    });

  return (
    <div className="wrap">
      <h1>ABOS</h1>
      <p className="sub">What&apos;s your mission? What&apos;s your budget? Launch.</p>

      {step === "auth" && (
        <div className="card">
          <div className="step">Step 0 · Account</div>
          <label>Email</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@startup.com" />
          <label>Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <div className="row">
            <button disabled={busy} onClick={() => doAuth(true)}>Sign up</button>
            <button className="ghost" disabled={busy} onClick={() => doAuth(false)}>Log in</button>
          </div>
        </div>
      )}

      {step === "mission" && (
        <div className="card">
          <div className="step">Step 1 · Mission &amp; Budget</div>
          <label>Mission</label>
          <textarea
            value={mission}
            onChange={(e) => setMission(e.target.value)}
            placeholder="Build the best vulnerability management platform for SMBs."
          />
          <label>Monthly budget (USD)</label>
          <input value={budget} onChange={(e) => setBudget(e.target.value)} />
          <button disabled={busy || !mission} onClick={startOnboarding}>Continue</button>
        </div>
      )}

      {step === "key" && (
        <div className="card">
          <div className="step">Step 2 · Bring your own key</div>
          <p className="muted">Your Claude API key is encrypted at rest. Only a fingerprint is ever shown.</p>
          <label>Anthropic API key</label>
          <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-ant-..." />
          <button disabled={busy || !apiKey} onClick={submitKeyAndGenerate}>
            {busy ? "Generating organization…" : "Generate organization"}
          </button>
        </div>
      )}

      {step === "review" && preview && (
        <div>
          <div className="card">
            <div className="step">Step 3 · Review generated organization</div>
            <h2>{preview.company.name}</h2>
            {preview.cost_estimate_cents != null && (
              <p className="muted">Est. monthly cost: {fmtUsd(preview.cost_estimate_cents)}</p>
            )}
            <h3>Objectives</h3>
            {preview.objectives.map((o) => (
              <div key={o.id} className="kv">
                <span>{o.title}</span>
                <span className="pill">P{o.priority}</span>
              </div>
            ))}
            <h3>Agent fleet</h3>
            {preview.org.agents.map((a) => (
              <div key={a.id} className="agent">
                <div className="role">{a.role}</div>
                <strong>{a.name}</strong>
                <div className="muted">
                  autonomy: {a.autonomy_level}
                  {a.monthly_budget_cents != null && ` · budget ${fmtUsd(a.monthly_budget_cents)}/mo`}
                </div>
              </div>
            ))}
          </div>
          <div className="card">
            <div className="step">Step 4 · Approve launch</div>
            <p className="muted">The company will start operating autonomously under your budget and governance.</p>
            <button disabled={busy} onClick={launch}>🚀 Launch Company</button>
          </div>
        </div>
      )}

      {err && <div className="err">{err}</div>}
    </div>
  );
}
