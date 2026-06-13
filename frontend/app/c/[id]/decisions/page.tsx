"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

export default function DecisionsPage() {
  const { id } = useParams<{ id: string }>();
  const [busy, setBusy] = useState<string | null>(null);
  const decisions = usePoll(() => api.decisions(id, true), 5000, [id]);

  const act = async (decisionId: string, approve: boolean) => {
    setBusy(decisionId);
    try {
      if (approve) await api.approveDecision(decisionId);
      else await api.rejectDecision(decisionId);
      await decisions.reload();
    } finally {
      setBusy(null);
    }
  };

  const list = decisions.data ?? [];

  return (
    <div>
      <h2>Decision inbox</h2>
      <p className="muted">Governance escalations and budget approvals that pause their task until you respond.</p>
      {list.length === 0 && <div className="empty">Nothing needs your approval. 🎉</div>}
      {list.map((d) => (
        <div key={d.id} className="card">
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span className="step">{d.kind}</span>
            <span className="muted" style={{ fontSize: 12 }}>{new Date(d.created_at).toLocaleString()}</span>
          </div>
          <p style={{ margin: "10px 0" }}>{d.summary}</p>
          <div className="btnrow">
            <button disabled={busy === d.id} onClick={() => act(d.id, true)}>Approve</button>
            <button className="ghost" disabled={busy === d.id} onClick={() => act(d.id, false)}>Reject</button>
          </div>
        </div>
      ))}
    </div>
  );
}
