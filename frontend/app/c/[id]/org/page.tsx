"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, fmtUsd, type Agent, type DataLabel } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

export default function OrgPage() {
  const { id } = useParams<{ id: string }>();
  const org = usePoll(() => api.org(id), 8000, [id]);
  const reputation = usePoll(() => api.reputation(id), 8000, [id]);
  const labels = usePoll(() => api.dataLabels(id), 0, [id]);

  const repByAgent = new Map((reputation.data ?? []).map((r) => [r.agent_id, r]));
  const agents = org.data?.agents ?? [];
  const ceo = agents.find((a) => a.role === "ceo");
  const others = agents.filter((a) => a.role !== "ceo");

  const toggle = async (a: Agent) => {
    if (a.status === "paused") await api.resumeAgent(id, a.id);
    else await api.pauseAgent(id, a.id);
    org.reload();
  };

  const Card = ({ a }: { a: Agent }) => {
    const r = repByAgent.get(a.id);
    const [showPrompt, setShowPrompt] = useState(false);
    return (
      <div className="agent">
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span className="role">{a.role}</span>
          <span className={`status ${a.status}`}>{a.status}</span>
        </div>
        <strong>{a.name}</strong>
        <div className="muted">
          {a.autonomy_level}
          {a.monthly_budget_cents != null && ` · ${fmtUsd(a.monthly_budget_cents)}/mo`}
          {r && r.sample_count > 0 && ` · trust ${(r.trust * 100).toFixed(0)}% · ROI ${(r.roi * 100).toFixed(0)}%`}
        </div>
        <div className="btnrow" style={{ marginTop: 10 }}>
          <button className="ghost" style={{ marginTop: 0 }} onClick={() => toggle(a)}>
            {a.status === "paused" ? "Resume" : "Pause"}
          </button>
          <button className="ghost" style={{ marginTop: 0 }} onClick={() => setShowPrompt((s) => !s)}>
            {showPrompt ? "Hide prompt" : "View prompt"}
          </button>
        </div>
        {showPrompt && (
          <div style={{ marginTop: 10 }}>
            <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Role</div>
            <pre className="prompt">{a.role_description || "(none)"}</pre>
            <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginTop: 8 }}>
              Company-specific directive
            </div>
            <pre className="prompt">{a.system_prompt || "(none set — the CEO can set one with set_agent_directive)"}</pre>
            <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
              This agent also runs under the company playbook above.
            </div>
          </div>
        )}
        <AccessEditor companyId={id} agent={a} labels={labels.data ?? []} onSaved={() => org.reload()} />
        <RuntimeEditor companyId={id} agent={a} onSaved={() => org.reload()} />
      </div>
    );
  };

  return (
    <div>
      <h2>Organization</h2>

      <Playbook companyId={id} />

      {ceo && <Card a={ceo} />}
      {others.length > 0 && <h3>Reports to {ceo?.name ?? "CEO"}</h3>}
      <div className="grid2">
        {others.map((a) => <Card key={a.id} a={a} />)}
      </div>
      {agents.length === 0 && <div className="empty">No agents yet.</div>}
    </div>
  );
}

// Per-agent data-access editor: which data labels this agent may be shown. The CEO
// bypasses segmentation entirely, so it shows a note instead of a picker. Sensitive
// labels the founder hasn't granted are simply unchecked; saving PUTs the new set.
function AccessEditor({
  companyId, agent, labels, onSaved,
}: { companyId: string; agent: Agent; labels: DataLabel[]; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState<Set<string>>(new Set(agent.access_labels ?? []));
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { setSel(new Set(agent.access_labels ?? [])); }, [agent.access_labels]);

  if (agent.role === "ceo") {
    return (
      <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
        🔓 Sees all company data (the CEO bypasses data segmentation).
      </div>
    );
  }

  const toggle = (key: string) =>
    setSel((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });

  const save = async () => {
    setBusy(true); setErr(null); setSaved(false);
    try {
      await api.setAgentAccessLabels(companyId, agent.id, [...sel]);
      setSaved(true);
      onSaved();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const current = agent.access_labels ?? [];
  return (
    <div style={{ marginTop: 10 }}>
      <div className="btnrow" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <span className="muted" style={{ fontSize: 12, fontWeight: 600 }}>
          Data access: {current.length ? current.join(", ") : "general only"}
        </span>
        <button className="ghost" style={{ marginTop: 0, padding: "4px 10px", fontSize: 12 }}
          onClick={() => setOpen((o) => !o)}>
          {open ? "Close" : "Manage access"}
        </button>
      </div>
      {open && (
        <div style={{ marginTop: 8 }}>
          {labels.length === 0 && <div className="muted" style={{ fontSize: 12 }}>No labels defined yet.</div>}
          {labels.map((l) => (
            <label key={l.key} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13, margin: "4px 0", fontWeight: 400 }}>
              <input type="checkbox" checked={sel.has(l.key)} disabled={busy} onChange={() => toggle(l.key)} />
              <span>
                <strong>{l.name}</strong>
                {l.description && <span className="muted"> — {l.description}</span>}
              </span>
            </label>
          ))}
          <div className="btnrow" style={{ marginTop: 8, alignItems: "center" }}>
            <button style={{ marginTop: 0 }} disabled={busy} onClick={save}>Save access</button>
            {saved && <span className="muted" style={{ fontSize: 12 }}>Saved.</span>}
            {err && <span className="err">{err}</span>}
          </div>
          <p className="muted" style={{ fontSize: 11, marginTop: 6 }}>
            Unlabelled data is general (everyone sees it). This agent is only shown data whose labels are all granted here.
          </p>
        </div>
      )}
    </div>
  );
}

// Where this function runs: 'native' (Galaxia's in-process loop) or 'external' (a
// connected worker — an OpenClaw Gateway or your own agent — over the Business-
// Function surface). Switching to external + minting a connection token is the
// "connect your own agent" flow (RFC 0001). The CEO runs natively (it orchestrates
// the company) and a marketplace agent's runtime is fixed by its listing.
// The three worker bindings from RFC 0001 §1a — one function slot, filled by an
// internal agent, an external agent, or a human — interchangeably.
const RUNTIMES: { key: "native" | "external" | "human"; label: string }[] = [
  { key: "native", label: "Native agent" },
  { key: "external", label: "External agent" },
  { key: "human", label: "Human" },
];

function RuntimeEditor({ companyId, agent, onSaved }: { companyId: string; agent: Agent; onSaved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [conn, setConn] = useState<{ token: string; mcp_url: string } | null>(null);

  if (agent.role === "ceo" || agent.backend_type === "marketplace") return null;
  const current = (agent.backend_type as "native" | "external" | "human") ?? "native";

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErr(null);
    try { await fn(); } catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
    finally { setBusy(false); }
  };

  return (
    <div style={{ marginTop: 12, borderTop: "1px solid rgba(128,128,128,0.15)", paddingTop: 10 }}>
      <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Runtime</div>
      <div className="btnrow" style={{ gap: 6 }}>
        {RUNTIMES.map((rt) => (
          <button key={rt.key} className={current === rt.key ? "" : "ghost"}
            style={{ marginTop: 0, padding: "4px 10px", fontSize: 12 }}
            disabled={busy || current === rt.key}
            onClick={() => run(async () => {
              await api.setAgentBackend(companyId, agent.id, rt.key);
              setConn(null); onSaved();
            })}>
            {rt.label}
          </button>
        ))}
      </div>
      {current === "external" && (
        <div style={{ marginTop: 8 }}>
          <button style={{ marginTop: 0 }} disabled={busy}
            onClick={() => run(async () => setConn(await api.mintConnection(companyId, agent.id)))}>
            Generate connection token
          </button>
          {conn && (
            <div className="card" style={{ marginTop: 8 }}>
              <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>
                Point your OpenClaw / MCP agent at this — the token is a secret, store it safely.
              </div>
              <pre className="prompt" style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
{`MCP URL: ${conn.mcp_url}
Bearer token: ${conn.token}`}
              </pre>
            </div>
          )}
          <p className="muted" style={{ fontSize: 11, marginTop: 6 }}>
            An external agent needs a connected worker (an OpenClaw Gateway or your own runtime). Until one is bound, this function&apos;s tasks report &quot;no runtime connected.&quot;
          </p>
        </div>
      )}
      {current === "human" && <HumanWorkPanel companyId={companyId} agent={agent} />}
      {err && <div className="err">{err}</div>}
    </div>
  );
}

// A person staffs this function: view its mandate + the initiative on deck, claim
// it, and report the outcome — the same loop an agent drives, rendered for a human.
function HumanWorkPanel({ companyId, agent }: { companyId: string; agent: Agent }) {
  const work = usePoll(() => api.functionWork(companyId, agent.id), 10000, [companyId, agent.id]);
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErr(null);
    try { await fn(); await work.reload(); } catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
    finally { setBusy(false); }
  };

  const w = work.data;
  const init = w?.initiative ?? null;
  const claimed = init?.status === "running";

  return (
    <div className="card" style={{ marginTop: 8 }}>
      <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>My work — {agent.name}</div>
      {w?.mandate?.constraints?.length ? (
        <p className="muted" style={{ fontSize: 11, marginTop: 4 }}>
          Constraints: {w.mandate.constraints.join(" · ")}
        </p>
      ) : null}
      {!init && <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>No initiative on deck.</p>}
      {init && (
        <div style={{ marginTop: 6 }}>
          <div style={{ fontSize: 13 }}><strong>Initiative:</strong> {init.goal}</div>
          <div className="muted" style={{ fontSize: 11 }}>status: {init.status}</div>
          {!claimed && (
            <button style={{ marginTop: 8 }} disabled={busy}
              onClick={() => run(() => api.claimWork(companyId, agent.id, init.id))}>
              Claim this initiative
            </button>
          )}
          {claimed && (
            <div style={{ marginTop: 8 }}>
              <input placeholder="One-line summary of the outcome" value={summary}
                onChange={(e) => setSummary(e.target.value)} style={{ width: "100%" }} />
              <div className="btnrow" style={{ marginTop: 6, gap: 6 }}>
                {["done", "blocked", "needs_decision"].map((outcome) => (
                  <button key={outcome} className={outcome === "done" ? "" : "ghost"}
                    style={{ marginTop: 0, padding: "4px 10px", fontSize: 12 }} disabled={busy}
                    onClick={() => run(async () => {
                      await api.reportWork(companyId, agent.id, init.id, outcome, summary);
                      setSummary("");
                    })}>
                    Report {outcome.replace("_", " ")}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      {err && <div className="err">{err}</div>}
    </div>
  );
}

// The company operating playbook is the global system prompt injected into EVERY
// agent's launch prompt. The CEO edits it autonomously (update_company_playbook) as
// directives emerge; the founder can view it here and override/reset it directly.
function Playbook({ companyId }: { companyId: string }) {
  const pb = usePoll(() => api.playbook(companyId), 0, [companyId]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (pb.data && !editing) setDraft(pb.data.playbook);
  }, [pb.data, editing]);

  const save = async () => {
    setBusy(true); setErr(null);
    try {
      await api.updatePlaybook(companyId, draft);
      setEditing(false);
      pb.reload();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (!window.confirm("Reset the playbook to the GalaxiaOS default? Your customizations will be lost.")) return;
    setBusy(true); setErr(null);
    try {
      await api.updatePlaybook(companyId, "");
      setEditing(false);
      pb.reload();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>Company playbook (global system prompt)</span>
        <span className={`status ${pb.data?.customized ? "active" : "pending"}`}>
          {pb.data?.customized ? "Customized" : "GalaxiaOS default"}
        </span>
      </div>
      <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
        The standing directives every agent is initialized with. The CEO keeps these current
        as the company learns; you can view and edit them here. Changes take effect on each
        agent&apos;s next task.
      </p>

      <button className="ghost" style={{ marginTop: 10 }} onClick={() => setOpen((o) => !o)}>
        {open ? "Hide" : "View"}
      </button>

      {open && !editing && (
        <>
          <pre className="prompt" style={{ marginTop: 10 }}>{pb.data?.playbook ?? "Loading…"}</pre>
          <div className="btnrow">
            <button style={{ marginTop: 0 }} onClick={() => { setDraft(pb.data?.playbook ?? ""); setEditing(true); }}>
              Edit
            </button>
            {pb.data?.customized && (
              <button className="ghost danger" style={{ marginTop: 0 }} disabled={busy} onClick={reset}>
                Reset to default
              </button>
            )}
          </div>
        </>
      )}

      {open && editing && (
        <>
          <textarea
            style={{ marginTop: 10, width: "100%", minHeight: 220, fontFamily: "monospace", fontSize: 13 }}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="btnrow">
            <button style={{ marginTop: 0 }} disabled={busy || !draft.trim()} onClick={save}>Save</button>
            <button className="ghost" style={{ marginTop: 0 }} disabled={busy} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
          {err && <div className="err">{err}</div>}
        </>
      )}
    </div>
  );
}
