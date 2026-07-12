"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, fmtUsd, type Company, type GenerationProgress, type InvestmentReview, type ManagedStatus, type Preview, type ReusableCredential } from "@/lib/api";
import { CloudflareCard, GoogleDriveCard, ReuseCredentialsCard } from "@/lib/connectors";

type Step = "loading" | "auth" | "businesses" | "mission" | "key" | "generating" | "review";
interface ChatTurn { who: "user" | "bot"; text: string }

export default function Home() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("loading");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [discarding, setDiscarding] = useState(false);

  // Set true while a draft is being discarded so an in-flight generation's
  // rejection (the company row is deleted out from under it) doesn't bounce us
  // back to the key step. Reset when a fresh generation intentionally starts.
  const discardingRef = useRef(false);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mission, setMission] = useState("");
  const [budget, setBudget] = useState("500");
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [tavilyKey, setTavilyKey] = useState("");
  const [resendKey, setResendKey] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);

  // Multi-business: a user can run several companies, listed after auth.
  const [businesses, setBusinesses] = useState<Company[]>([]);

  // Generation telemetry.
  const [progress, setProgress] = useState<GenerationProgress | null>(null);

  // Reuse of keys/connections saved on the founder's other businesses. Populated
  // when we land on the "key" step; `reusedKeyProviders` tracks which raw keys
  // (e.g. "anthropic") are now present so we don't force re-typing them, and
  // `reuseNonce` remounts the connector cards after a reuse so they re-fetch.
  const [reusable, setReusable] = useState<ReusableCredential[]>([]);
  const [reusedKeyProviders, setReusedKeyProviders] = useState<string[]>([]);
  const [reuseNonce, setReuseNonce] = useState(0);

  // Managed mode: whether the platform will fund this founder's compute so they
  // can launch with no key at all (hosted "no keys needed" tier).
  const [managed, setManaged] = useState<ManagedStatus | null>(null);

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
  // onboarding; an account with businesses lands on its list.
  async function afterAuth() {
    const list = await api.myCompanies();
    setBusinesses(list);
    setStep(list.length > 0 ? "businesses" : "mission");
  }

  // Open a company: a draft hasn't been launched yet, so resume it at the plan-
  // approval (review) screen — load its generated plan and let the founder launch
  // — instead of dropping into a dashboard for a company that isn't live. A
  // launched (active/paused/…) company goes straight to its Game — the default
  // screen for a live company.
  async function openCompany(c: Company) {
    if (c.status === "draft") {
      const p = await api.preview(c.id);
      setCompanyId(c.id);
      setPreview(p);
      setStep("review");
      return;
    }
    router.push(`/c/${c.id}/game`);
  }

  // Bootstrap: consume a Google SSO redirect, else reuse an existing session,
  // else show the sign-in screen. A stale/expired token is cleared rather than
  // blocking the sign-in screen.
  useEffect(() => {
    let cancelled = false;

    (async () => {
      // 0) Returning from Google SSO: the backend redirects to "/?token=…" with a
      //    fresh access token (or "?auth=denied|error" on failure). Consume it,
      //    strip it from the address bar so it isn't bookmarked/shared, then route.
      if (typeof window !== "undefined") {
        const params = new URLSearchParams(window.location.search);
        const ssoToken = params.get("token");
        const authErr = params.get("auth");
        if (ssoToken || authErr) {
          window.history.replaceState({}, "", window.location.pathname);
        }
        if (ssoToken) {
          api.setToken(ssoToken);
          try {
            await afterAuth();
            return;
          } catch {
            api.logout();
          }
        } else if (authErr) {
          setErr(authErr === "denied" ? "Google sign-in was cancelled." : "Google sign-in failed. Please try again.");
          if (!cancelled) setStep("auth");
          return;
        }
      }
      // 1) Reuse an existing session — but a stale/expired token must not block
      //    the sign-in screen. If it fails, drop it and fall through.
      if (api.hasToken()) {
        try {
          await afterAuth();
          return;
        } catch {
          api.logout();
        }
      }
      if (cancelled) return;
      // 2) Sign-in screen (Google SSO by default; email/password fallback).
      if (!cancelled) setStep("auth");
    })();

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // On the BYOK step, offer any keys/connections saved on the founder's other
  // businesses for one-click reuse. Runs whenever we (re)enter the step for a
  // company; after a reuse the target already has them, so the list comes back
  // empty and the card hides itself.
  useEffect(() => {
    if (step !== "key" || !companyId) return;
    let cancelled = false;
    api.reusableCredentials(companyId)
      .then((items) => { if (!cancelled) setReusable(items); })
      .catch(() => { if (!cancelled) setReusable([]); });
    api.managedStatus(companyId)
      .then((s) => { if (!cancelled) setManaged(s); })
      .catch(() => { if (!cancelled) setManaged(null); });
    return () => { cancelled = true; };
  }, [step, companyId, reuseNonce]);

  const doAuth = (signup: boolean) =>
    guard(async () => {
      const res = signup ? await api.signup(email, password) : await api.login(email, password);
      api.setToken(res.access_token);
      await afterAuth();
    });

  // Whether "Continue with Google" is available on this deployment.
  const [googleEnabled, setGoogleEnabled] = useState(false);
  useEffect(() => {
    api.googleAuthStatus().then((s) => setGoogleEnabled(s.enabled)).catch(() => setGoogleEnabled(false));
  }, []);

  // Redirect the whole page to Google's consent screen. On return the backend
  // bounces back to "/?token=…", which the bootstrap effect below consumes.
  const doGoogle = () =>
    guard(async () => {
      const { authorize_url } = await api.googleAuthorizeUrl();
      window.location.href = authorize_url;
    });

  // Clear every field the onboarding wizard collects so the next run starts clean.
  const resetWizard = () => {
    setCompanyId(null); setApiKey(""); setTavilyKey(""); setResendKey(""); setPreview(null);
    setChat([]); setProgress(null); setMission(""); setBudget("500"); setErr(null);
    setReusable([]); setReusedKeyProviders([]); setManaged(null);
  };

  const newBusiness = () => {
    resetWizard();
    setStep("mission");
  };

  // Discard the in-progress draft company and return to the main page. The draft
  // exists once onboarding has started (the "key", "generating" and "review"
  // steps), so this permanently deletes it; then we land on the founder's
  // business list (or a fresh mission screen if they have none).
  const discardDraft = async () => {
    if (typeof window !== "undefined" &&
        !window.confirm("Discard this draft company and delete its generated plan? This can't be undone.")) {
      return;
    }
    setErr(null); setDiscarding(true);
    discardingRef.current = true;
    try {
      if (companyId) await api.deleteCompany(companyId);
      resetWizard();
      const list = await api.myCompanies();
      setBusinesses(list);
      setStep(list.length > 0 ? "businesses" : "mission");
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setDiscarding(false);
    }
  };

  const startOnboarding = () =>
    guard(async () => {
      const c = await api.startOnboarding(mission, Math.round(parseFloat(budget) * 100), []);
      setCompanyId(c.id);
      setStep("key");
    });

  // A key is no longer strictly required: on the hosted managed tier the platform
  // funds generation, so a founder can launch with nothing. A key is satisfied by
  // typing one now or reusing one from another business; otherwise managed mode
  // (when available and within the free allowance) covers it.
  const hasAnthropicKey = apiKey.trim().length > 0 || reusedKeyProviders.includes("anthropic");
  const managedCovers = !!(managed?.managed_mode && managed?.allowed);
  const canGenerate = hasAnthropicKey || managedCovers;

  // Kick off generation and poll for progress telemetry in parallel.
  const submitKeyAndGenerate = () =>
    guard(async () => {
      if (!companyId) return;
      discardingRef.current = false; // a fresh, intentional generation
      // A freshly typed key wins (lets the founder override a reused one); if they
      // reused an Anthropic key and typed nothing, it's already stored.
      if (apiKey.trim()) await api.addApiKey(companyId, apiKey.trim());
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
        // If the founder discarded the draft mid-generation, the company was
        // deleted out from under this call — stay on the main page instead of
        // bouncing back to the key step for a company that no longer exists.
        if (discardingRef.current) return;
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
      // Land the founder in the Game — the default screen once a company is
      // live — so onboarding hands straight off to operating the starbase.
      router.push(`/c/${companyId}/game?launched=1`);
    });

  // A compact "discard draft" control shown on every onboarding step that has a
  // live draft, so the founder can bail out and return to the main page.
  const discardButton = (
    <button
      className="ghost danger"
      style={{ marginTop: 0, padding: "6px 12px", fontSize: 12 }}
      disabled={discarding}
      onClick={discardDraft}
    >
      {discarding ? "Discarding…" : "Discard draft"}
    </button>
  );

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

          {googleEnabled && (
            <>
              <button disabled={busy} onClick={doGoogle} style={{ width: "100%" }}>
                Continue with Google
              </button>
              <p className="muted" style={{ fontSize: 12, margin: "6px 0 0", textAlign: "center" }}>
                The fastest way in. You can connect Google Drive account-wide afterwards, so every
                business you launch files into your own Drive.
              </p>
              <div className="or-divider" style={{ display: "flex", alignItems: "center", gap: 10, margin: "16px 0" }}>
                <span style={{ flex: 1, height: 1, background: "var(--border, rgba(255,255,255,0.15))" }} />
                <span className="muted" style={{ fontSize: 12 }}>or with email</span>
                <span style={{ flex: 1, height: 1, background: "var(--border, rgba(255,255,255,0.15))" }} />
              </div>
            </>
          )}

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
              onClick={() => guard(() => openCompany(b))}
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

      {step === "key" && companyId && reusable.length > 0 && (
        <ReuseCredentialsCard
          companyId={companyId}
          items={reusable}
          onReused={(reusedIds) => {
            // Note which raw keys are now present (so we don't force re-typing),
            // then bump the nonce to re-fetch the (now shorter) reuse list and
            // remount the connector cards so they reflect the copied connections.
            const providers = reusedIds
              .filter((id) => id.startsWith("key:"))
              .map((id) => id.slice("key:".length));
            setReusedKeyProviders((prev) => Array.from(new Set([...prev, ...providers])));
            setReuseNonce((n) => n + 1);
          }}
        />
      )}

      {step === "key" && (
        <div className="card">
          <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>Step 2 · {managedCovers && !hasAnthropicKey ? "Launch — no keys needed" : "Keys"}</span>
            {discardButton}
          </div>

          {/* Managed tier: lead with "you can just launch" when the platform will
              fund it. Only shown on a deployment with managed mode configured. */}
          {managed?.managed_mode && managed.configured && (
            <div className={`card ${managed.allowed ? "" : "muted"}`} style={{ marginTop: 4, background: "rgba(120,180,255,0.06)" }}>
              {managed.allowed ? (
                <>
                  <strong>✨ You&apos;re on the free managed tier</strong>
                  <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
                    No keys required — the platform runs your fleet on us up to{" "}
                    {fmtUsd(managed.free_allowance_cents)} of usage
                    {managed.free_remaining_cents < managed.free_allowance_cents &&
                      ` (${fmtUsd(managed.free_remaining_cents)} left)`}. Bring your own model key
                    anytime to remove the cap and run on your own account.
                  </p>
                </>
              ) : (
                <>
                  <strong>Free managed allowance used up</strong>
                  <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
                    {managed.reason ?? "Add your own model key below, or upgrade to managed in Settings."}
                  </p>
                </>
              )}
            </div>
          )}

          {reusedKeyProviders.includes("anthropic") ? (
            <p className="muted" style={{ fontSize: 13, marginTop: 10 }}>
              ✓ Reused your Anthropic key from another business. You can generate now, or paste a
              different key below to override it.
            </p>
          ) : null}

          {/* The key inputs stay available but are optional under managed mode.
              Collapse them behind a disclosure so the default path is "just launch". */}
          <details open={!managedCovers || hasAnthropicKey} style={{ marginTop: 10 }}>
            <summary style={{ cursor: "pointer", fontSize: 14 }}>
              {managedCovers ? "Advanced · Use your own keys (optional)" : "Bring your own key"}
            </summary>
            <div style={{ marginTop: 10 }}>
              <p className="muted" style={{ fontSize: 12 }}>
                Your keys are encrypted at rest. Only a fingerprint is ever shown. A model key runs
                the fleet on your own account (no platform cap).
              </p>
              <label>Anthropic API key {(reusedKeyProviders.includes("anthropic") || managedCovers) && <span className="muted">(optional)</span>}</label>
              <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-ant-..." />
              <label>Tavily API key <span className="muted">(optional)</span></label>
              <input type="password" value={tavilyKey} onChange={(e) => setTavilyKey(e.target.value)} placeholder="tvly-… — enables real web search" />
              <label>Resend API key <span className="muted">(optional)</span></label>
              <input type="password" value={resendKey} onChange={(e) => setResendKey(e.target.value)} placeholder="re_… — send real email from your domain (free tier)" />
              <p className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                Without Tavily, web search {managedCovers ? "uses the platform default" : "returns simulated results"};
                without Resend, email is simulated. You can add or change these later in Settings.
              </p>
            </div>
          </details>

          <button disabled={busy || !canGenerate} onClick={submitKeyAndGenerate}>
            {managedCovers && !hasAnthropicKey ? "Launch — generate organization" : "Generate organization"}
          </button>
          {!canGenerate && (
            <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>
              Add a model key above to generate{managed?.managed_mode ? " (free managed tier isn't available for this account)" : ""}.
            </p>
          )}
        </div>
      )}

      {step === "key" && companyId && (
        <div>
          <div className="step" style={{ marginTop: 18 }}>Optional · Connect your tools</div>
          <p className="muted" style={{ fontSize: 13, margin: "4px 0 10px" }}>
            Hook up hosting and a file store now, or skip and do it later in Settings — neither is
            required to generate or launch your organization.
          </p>
          {/* `reuseNonce` in the key remounts these after a reuse so they re-fetch
              status and reflect a connection that was just copied over. */}
          <CloudflareCard key={`cf-${reuseNonce}`} companyId={companyId} />
          {/* Popup mode keeps this onboarding wizard intact across Google's consent
              round-trip instead of navigating the whole page away. */}
          <GoogleDriveCard key={`gd-${reuseNonce}`} companyId={companyId} popup />
        </div>
      )}

      {step === "generating" && (
        <>
          <GeneratingCard progress={progress} />
          <div style={{ display: "flex", justifyContent: "center", marginTop: 12 }}>{discardButton}</div>
        </>
      )}

      {step === "review" && preview && (
        <div>
          <div className="card">
            <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>Step 3 · Review generated organization</span>
              {discardButton}
            </div>
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
