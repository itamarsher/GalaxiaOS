"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, fmtUsd, type Company, type GenerationProgress, type InvestmentReview, type Preview } from "@/lib/api";
import { CloudflareCard, GoogleDriveCard } from "@/lib/connectors";

type Step = "loading" | "auth" | "businesses" | "mission" | "key" | "generating" | "review";
interface ChatTurn { who: "user" | "bot"; text: string }

export default function Home() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("loading");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mission, setMission] = useState("");
  const [budget, setBudget] = useState("500");
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [githubKey, setGithubKey] = useState("");
  const [tavilyKey, setTavilyKey] = useState("");
  const [resendKey, setResendKey] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);

  // Multi-business: a user can run several companies, listed after auth.
  const [businesses, setBusinesses] = useState<Company[]>([]);

  // Generation telemetry.
  const [progress, setProgress] = useState<GenerationProgress | null>(null);

  // Refinement chat.
  const [chat, setChat] = useState<ChatTurn[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [refining, setRefining] = useState(false);

  async function guard(fn: () => Promise<void>) {
    setErr(null); setBusy(true);
    try { await fn(); } catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
    finally { setBusy(false); }
  }

  // After authentication, route to the right place: a fresh account starts
  // onboarding; an account with businesses lands on its list. When we got here
  // via the dev auto-login and a business already exists, jump straight to its
  // dashboard (fast iteration — no clicks).
  async function afterAuth(autoLoggedIn: boolean) {
    const list = await api.myCompanies();
    setBusinesses(list);
    if (autoLoggedIn && list.length > 0) {
      router.push(`/c/${list[0].id}`);
      return;
    }
    setStep(list.length > 0 ? "businesses" : "mission");
  }

  // Bootstrap: use an existing session; else try the dev default account
  // (auto-login); else fall back to the normal auth screen. Each step is
  // resilient: a stale/expired token is cleared rather than blocking
  // auto-login, and a cold-started API (Render free tier spins down) is
  // retried so it isn't mistaken for "dev tools disabled".
  useEffect(() => {
    let cancelled = false;

    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

    // Auto-login as the dev default account. Returns true if it handled
    // navigation (logged in OR dev genuinely disabled), false to keep trying.
    async function tryDevAutoLogin(): Promise<boolean> {
      for (let attempt = 0; attempt < 3 && !cancelled; attempt++) {
        try {
          const status = await api.devStatus();
          if (!status.enabled) return false; // dev off -> normal auth screen
          const res = await api.defaultLogin();
          if (cancelled) return true;
          api.setToken(res.access_token);
          await afterAuth(true);
          return true;
        } catch {
          // Network/cold-start error: wait and retry before giving up so a
          // spun-down API doesn't silently bounce us to the login screen.
          if (attempt < 2) await sleep(1500);
        }
      }
      return false;
    }

    (async () => {
      // 1) Reuse an existing session — but a stale/expired token must not
      //    block auto-login. If it fails, drop it and fall through.
      if (api.hasToken()) {
        try {
          await afterAuth(false);
          return;
        } catch {
          api.logout();
        }
      }
      if (cancelled) return;
      // 2) Dev convenience: auto-login as the default account.
      if (await tryDevAutoLogin()) return;
      // 3) Normal auth screen.
      if (!cancelled) setStep("auth");
    })();

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const doAuth = (signup: boolean) =>
    guard(async () => {
      const res = signup ? await api.signup(email, password) : await api.login(email, password);
      api.setToken(res.access_token);
      await afterAuth(false);
    });

  const newBusiness = () => {
    // Reset the onboarding wizard so creating an Nth business starts clean.
    setCompanyId(null); setApiKey(""); setGithubKey(""); setTavilyKey(""); setResendKey(""); setPreview(null);
    setChat([]); setProgress(null); setMission(""); setBudget("500"); setErr(null);
    setStep("mission");
  };

  const startOnboarding = () =>
    guard(async () => {
      const c = await api.startOnboarding(mission, Math.round(parseFloat(budget) * 100), []);
      setCompanyId(c.id);
      setStep("key");
    });

  // Kick off generation and poll for progress telemetry in parallel.
  const submitKeyAndGenerate = () =>
    guard(async () => {
      if (!companyId) return;
      await api.addApiKey(companyId, apiKey);
      // Optional: a GitHub token lets the platform agent file real issues.
      if (githubKey.trim()) await api.addApiKey(companyId, githubKey.trim(), "github");
      // Optional: a Tavily key enables real web search (else it's simulated).
      if (tavilyKey.trim()) await api.addApiKey(companyId, tavilyKey.trim(), "tavily");
      // Optional: a Resend key makes Resend the email provider (else simulated).
      if (resendKey.trim()) await api.addApiKey(companyId, resendKey.trim(), "resend");
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
      <div className="brand-hero">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/galaxiaos-logo.png" alt="GalaxiaOS logo" className="brand-hero-logo" width={56} height={56} />
        <h1>GalaxiaOS</h1>
      </div>
      <p className="sub">What&apos;s your mission? What&apos;s your budget? Launch.</p>

      {step === "loading" && (
        <div className="card">
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span className="spinner" /> <span className="muted">Loading…</span>
          </div>
        </div>
      )}

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

      {step === "businesses" && (
        <div className="card">
          <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>Your businesses</span>
            <button style={{ marginTop: 0, padding: "6px 12px", fontSize: 13 }} onClick={newBusiness}>+ New business</button>
          </div>
          <p className="muted" style={{ fontSize: 13 }}>Run as many companies as you like from one account.</p>
          {businesses.map((b) => (
            <button
              key={b.id}
              className="ghost"
              style={{ display: "flex", justifyContent: "space-between", width: "100%", marginTop: 8 }}
              onClick={() => router.push(`/c/${b.id}`)}
            >
              <span>{b.name}</span>
              <span className={`status ${b.status}`}>{b.status}</span>
            </button>
          ))}
        </div>
      )}

      {step === "mission" && (
        <div className="card">
          <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>Step 1 · Mission &amp; Budget</span>
            {businesses.length > 0 && (
              <button className="ghost" style={{ marginTop: 0, padding: "6px 12px", fontSize: 12 }}
                onClick={() => setStep("businesses")}>← Your businesses</button>
            )}
          </div>
          <label>Mission</label>
          <textarea
            value={mission}
            onChange={(e) => setMission(e.target.value)}
            placeholder="Build the best vulnerability management platform for SMBs."
          />
          <label>Initial budget (USD)</label>
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
          <label>Tavily API key <span className="muted">(optional)</span></label>
          <input type="password" value={tavilyKey} onChange={(e) => setTavilyKey(e.target.value)} placeholder="tvly-… — enables real web search" />
          <label>Resend API key <span className="muted">(optional)</span></label>
          <input type="password" value={resendKey} onChange={(e) => setResendKey(e.target.value)} placeholder="re_… — send real email from your domain (free tier)" />
          <p className="muted" style={{ fontSize: 12, marginTop: 4 }}>
            Optional. Without GitHub, bug/capability requests use an offline tracker; without
            Tavily, web search returns simulated results; without Resend, email is simulated. You
            can add or change these later in Settings.
          </p>
          <button disabled={busy || !apiKey} onClick={submitKeyAndGenerate}>
            Generate organization
          </button>
        </div>
      )}

      {step === "key" && companyId && (
        <div>
          <div className="step" style={{ marginTop: 18 }}>Optional · Connect your tools</div>
          <p className="muted" style={{ fontSize: 13, margin: "4px 0 10px" }}>
            Hook up hosting and a file store now, or skip and do it later in Settings — neither is
            required to generate or launch your organization.
          </p>
          <CloudflareCard companyId={companyId} />
          {/* Popup mode keeps this onboarding wizard intact across Google's consent
              round-trip instead of navigating the whole page away. */}
          <GoogleDriveCard companyId={companyId} popup />
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

          {(preview.investment_reviews?.length ?? 0) > 0 && (
            <div className="card">
              <div className="step">Investor review · Three takes on your venture</div>
              <p className="muted">
                Three agentic investors weighed your plan through different lenses. Use their
                verdicts to refine above before you launch.
              </p>
              {[...preview.investment_reviews]
                .sort((a, b) => personaOrder(a.persona) - personaOrder(b.persona))
                .map((r) => (
                  <InvestorReviewItem key={r.id} review={r} />
                ))}
            </div>
          )}

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

// Investor review presentation. The backend persists three personas; we show
// them in a stable order with a friendly label and a stance-coloured verdict.
const PERSONA_META: Record<string, { label: string; order: number }> = {
  small_business: { label: "Small-business investor", order: 0 },
  startup: { label: "Venture (VC) investor", order: 1 },
  devils_advocate: { label: "Devil's advocate", order: 2 },
};
const STANCE_LABEL: Record<string, string> = {
  invest: "Invest",
  conditional: "Conditional",
  pass: "Pass",
};

function personaOrder(persona: string): number {
  return PERSONA_META[persona]?.order ?? 99;
}

function InvestorReviewItem({ review }: { review: InvestmentReview }) {
  const persona = PERSONA_META[review.persona]?.label ?? review.persona;
  return (
    <div className="review">
      <div className="review-head">
        <strong>{persona}</strong>
        <span className={`stance ${review.stance}`}>
          {STANCE_LABEL[review.stance] ?? review.stance} · {review.conviction}%
        </span>
      </div>
      <div className="review-headline">{review.headline}</div>
      {review.thesis && <p className="muted">{review.thesis}</p>}
      {review.strengths && review.strengths.length > 0 && (
        <ReviewList label="Strengths" items={review.strengths} />
      )}
      {review.risks && review.risks.length > 0 && (
        <ReviewList label="Risks" items={review.risks} />
      )}
      {review.conditions && review.conditions.length > 0 && (
        <ReviewList label="Conditions" items={review.conditions} />
      )}
    </div>
  );
}

function ReviewList({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="review-list">
      <h4>{label}</h4>
      <ul>
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
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
