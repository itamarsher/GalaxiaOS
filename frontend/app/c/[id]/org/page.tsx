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
