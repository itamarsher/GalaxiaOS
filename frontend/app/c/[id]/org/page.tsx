"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, fmtUsd, type Agent } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

export default function OrgPage() {
  const { id } = useParams<{ id: string }>();
  const org = usePoll(() => api.org(id), 8000, [id]);
  const reputation = usePoll(() => api.reputation(id), 8000, [id]);

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
