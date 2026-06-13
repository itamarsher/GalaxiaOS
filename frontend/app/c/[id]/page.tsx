"use client";

import { useParams } from "next/navigation";
import { api, fmtUsd } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

export default function Overview() {
  const { id } = useParams<{ id: string }>();
  const company = usePoll(() => api.company(id), 0, [id]);
  const budget = usePoll(() => api.budget(id), 5000, [id]);
  const decisions = usePoll(() => api.decisions(id, true), 5000, [id]);
  const digest = usePoll(() => api.digestLatest(id), 0, [id]);

  const b = budget.data?.budget;
  const pct = b && b.limit_cents ? Math.min(100, (b.spent_cents / b.limit_cents) * 100) : 0;

  return (
    <div>
      <h2>{company.data?.name ?? "Company"}</h2>
      <p className="muted">
        Status: <span className={`status ${company.data?.status}`}>{company.data?.status ?? "—"}</span>
      </p>

      <div className="grid2">
        <div className="card">
          <div className="step">Budget</div>
          {b ? (
            <>
              <div className="kv"><span>Spent</span><span>{fmtUsd(b.spent_cents)} / {fmtUsd(b.limit_cents)}</span></div>
              <div className="bar" style={{ marginTop: 8 }}><span style={{ width: `${pct}%` }} /></div>
              <div className="kv" style={{ marginTop: 8 }}><span>Reserved</span><span>{fmtUsd(b.reserved_cents)}</span></div>
            </>
          ) : <p className="muted">loading…</p>}
        </div>

        <div className="card">
          <div className="step">Decisions needed</div>
          <p style={{ fontSize: 32, margin: "8px 0" }}>{decisions.data?.length ?? 0}</p>
          <p className="muted">Pending founder approvals. See the Decisions tab.</p>
        </div>
      </div>

      <div className="card">
        <div className="step" style={{ display: "flex", justifyContent: "space-between" }}>
          <span>Latest digest{digest.data?.period_date ? ` · ${digest.data.period_date}` : ""}</span>
        </div>
        {digest.data?.summary_md ? (
          <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: "8px 0 0" }}>
            {digest.data.summary_md}
          </pre>
        ) : (
          <div className="empty">
            No digest yet.
            <div style={{ marginTop: 8 }}>
              <button onClick={() => api.generateDigest(id).then(() => digest.reload())}>
                Generate now
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
