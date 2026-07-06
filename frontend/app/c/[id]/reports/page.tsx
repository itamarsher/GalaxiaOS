"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { api, type Artifact } from "@/lib/api";
import { usePoll } from "@/lib/useApi";
import { Markdown } from "@/lib/markdown";

// Founder-facing deliverables agents file via `create_report`, plus on-demand
// generation grounded in real company state.
const KINDS: { value: string; label: string }[] = [
  { value: "investor_update", label: "Investor update" },
  { value: "growth_report", label: "Growth report" },
  { value: "research_report", label: "Research report" },
  { value: "board_brief", label: "Board brief" },
  { value: "custom", label: "Custom" },
];

export default function ReportsPage() {
  const { id } = useParams<{ id: string }>();
  const reports = usePoll(() => api.reports(id), 15000, [id]);
  const [open, setOpen] = useState<Artifact | null>(null);
  const [kind, setKind] = useState("investor_update");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const generate = async () => {
    setBusy(true); setErr(null);
    try {
      const a = await api.generateReport(id, kind);
      setOpen(a);
      reports.reload();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const view = async (rid: string) => {
    try { setOpen(await api.report(id, rid)); }
    catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
  };

  const list = reports.data ?? [];

  return (
    <div>
      <h2>Reports</h2>
      <p className="muted">
        Synthesized deliverables for you to read — agents file these as they work, and you can
        generate one on demand. Reports are internal: generating one never sends anything externally.
      </p>

      <div className="card">
        <div className="step">Generate a report</div>
        <label>Kind</label>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
        </select>
        <div className="btnrow">
          <button disabled={busy} onClick={generate}>{busy ? "Generating…" : "Generate"}</button>
        </div>
        {err && <div className="err">{err}</div>}
      </div>

      {open && (
        <div className="card">
          <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>{open.title}</span>
            <button className="ghost" style={{ marginTop: 0 }} onClick={() => setOpen(null)}>Close</button>
          </div>
          <div className="muted" style={{ fontSize: 13 }}>{open.kind.replace(/_/g, " ")}</div>
          <Markdown className="digest-md">{open.body_md}</Markdown>
        </div>
      )}

      {list.length === 0 && !reports.loading && (
        <p className="muted">No reports yet. Agents will file them as they synthesize work, or generate one above.</p>
      )}
      {list.map((r) => (
        <div key={r.id} className="card" style={{ cursor: "pointer" }} onClick={() => view(r.id)}>
          <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>{r.title}</span>
            <span className="status">{r.kind.replace(/_/g, " ")}</span>
          </div>
          <div className="muted" style={{ fontSize: 13 }}>{new Date(r.created_at).toLocaleString()}</div>
        </div>
      ))}
    </div>
  );
}
