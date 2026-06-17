"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, fmtUsd, type GenerationProgress, type Preview } from "@/lib/api";

type Step = "auth" | "mission" | "key" | "generating" | "review";
interface ChatTurn { who: "user" | "bot"; text: string }

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
  const [githubKey, setGithubKey] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);

  // Generation telemetry (task 1).
  const [progress, setProgress] = useState<GenerationProgress | null>(null);

  // Refinement chat (task 2).
  const [chat, setChat] = useState<ChatTurn[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [refining, setRefining] = useState(false);

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

  // TEMP dev tool — remove before launch. Wipes every account and all its data.
  const wipeAllAccounts = () =>
    guard(async () => {
      if (!window.confirm("DELETE ALL ACCOUNTS and every company/agent/task they own? This cannot be undone.")) return;
      const res = await api.deleteAllAccounts();
      api.logout();
      alert(`Deleted ${res.deleted_accounts} account(s). The database is now empty.`);
    });

  const startOnboarding = () =>
    guard(async () => {
      const c = await api.startOnboarding(mission, Math.round(parseFloat(budget) * 100), []);
      setCompanyId(c.id);
      setStep("key");
    });

  // Kick off generation and poll for progress telemetry in parallel. The POST is
  // a single long request; while it runs we poll the status endpoint so the
  // founder sees a live spinner with real phases instead of a frozen button.
  const submitKeyAndGenerate = () =>
    guard(async () => {
      if (!companyId) return;
      await api.addApiKey(companyId, apiKey);
      // Optional: a GitHub token lets the platform agent file real issues.
      if (githubKey.trim()) await api.addApiKey(companyId, githubKey.trim(), "github");
      setProgress({ phase: "queued", pct: 0, message: "Starting…", status: "running", error: null, events: [] });
      setStep("generating");
      const poll = setInterval(async () => {
        try { setProgress(await api.generateStatus(companyId)); } catch { /* keep last */ }
      }, 1000);
      try {
        const p = await api.generate(companyId);
        setPreview(p);
        setStep("review");
      } catch (e) {
        setStep("key"); // let them retry
        throw e;
      } finally {
        clearInterval(poll);
      }
    });

  const sendRefine = async () => {
    const q = chatInput.trim();
    if (!q || refining || !companyId) return;
    setChatInput("");
    setChat((c) => [...c, { who: "user", text: q }]);
    setRefining(true);
    try {
      const res = await api.refineOnboarding(companyId, q);
      // Refinement doesn't recompute the cost estimate, so keep the prior one.
      setPreview((prev) => ({
        ...res.preview,
        cost_estimate_cents: res.preview.cost_estimate_cents ?? prev?.cost_estimate_cents ?? null,
      }));
      setChat((c) => [...c, { who: "bot", text: res.reply }]);
    } catch (e) {
      setChat((c) => [...c, { who: "bot", text: String(e instanceof Error ? e.message : e) }]);
    } finally {
      setRefining(false);
    }
  };

  const launch = () =>
    guard(async () => {
      if (!companyId) return;
      await api.launch(companyId);
      router.push(`/c/${companyId}?launched=1`);
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

          {/* TEMP DEV TOOL — remove before launch (also: backend app/api/dev.py + ABOS_DEV_TOOLS_ENABLED). */}
          <div style={{ marginTop: 20, paddingTop: 14, borderTop: "1px dashed var(--border)" }}>
            <p className="muted" style={{ fontSize: 12, margin: "0 0 8px" }}>
              ⚠️ Dev only — wipes the entire database. Remove before going live.
            </p>
            <button className="ghost danger" disabled={busy} onClick={wipeAllAccounts}>
              Delete ALL accounts
            </button>
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
          <label>GitHub token <span className="muted">(optional)</span></label>
          <input type="password" value={githubKey} onChange={(e) => setGithubKey(e.target.value)} placeholder="ghp_… — lets the platform agent file real issues" />
          <p className="muted" style={{ fontSize: 12, marginTop: 4 }}>
            Optional. Without it, bug/capability requests are filed to an offline tracker.
            You can add or change this later in Settings.
          </p>
          <button disabled={busy || !apiKey} onClick={submitKeyAndGenerate}>
            Generate organization
          </button>
        </div>
      )}

      {step === "generating" && <GeneratingCard progress={progress} />}

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
            <div className="step">Refine · Chat to change the plan</div>
            <p className="muted">
              Not quite right? Ask for changes — e.g. &ldquo;drop the finance agent&rdquo; or
              &ldquo;add an objective about enterprise sales&rdquo;.
            </p>
            {chat.length > 0 && (
              <div className="chat" style={{ marginBottom: 12 }}>
                {chat.map((t, i) => (
                  <div key={i} className={`msg ${t.who}`}>{t.text}</div>
                ))}
                {refining && <div className="msg bot muted">updating the plan…</div>}
              </div>
            )}
            <div className="chatbar">
              <input
                placeholder="Ask for a change…"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendRefine()}
                disabled={refining}
              />
              <button onClick={sendRefine} disabled={refining || !chatInput.trim()}>Send</button>
            </div>
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

function GeneratingCard({ progress }: { progress: GenerationProgress | null }) {
  const logRef = useRef<HTMLDivElement>(null);
  const pct = progress?.pct ?? 0;
  const events = progress?.events ?? [];

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [events.length]);

  return (
    <div className="card">
      <div className="step">Step 2 · Generating your organization</div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, margin: "14px 0 6px" }}>
        <span className="spinner" />
        <strong>{progress?.message ?? "Starting…"}</strong>
      </div>
      <div className="bar" style={{ marginTop: 8 }}><span style={{ width: `${pct}%` }} /></div>
      <div className="kv" style={{ marginTop: 8 }}>
        <span className="muted">It usually takes a couple of minutes.</span>
        <span className="muted">{pct}%</span>
      </div>
      {events.length > 0 && (
        <div ref={logRef} className="genlog">
          {events.map((e, i) => (
            <div key={i} className="genlog-row">
              <span className="genlog-dot" />
              <span>{e.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
