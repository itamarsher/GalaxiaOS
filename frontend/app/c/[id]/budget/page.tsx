"use client";

import { useParams } from "next/navigation";
import { api, fmtUsd } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

export default function BudgetPage() {
  const { id } = useParams<{ id: string }>();
  const budget = usePoll(() => api.budget(id), 4000, [id]);
  const runway = usePoll(() => api.runway(id), 4000, [id]);

  const b = budget.data?.budget;

  return (
    <div>
      <h2>Budget OS</h2>
      <div className="grid2">
        <div className="card">
          <div className="step">Spend</div>
          {b ? (
            <>
              <div className="kv"><span>Limit</span><span>{fmtUsd(b.limit_cents)}</span></div>
              <div className="kv"><span>Spent</span><span>{fmtUsd(b.spent_cents)}</span></div>
              <div className="kv"><span>Reserved</span><span>{fmtUsd(b.reserved_cents)}</span></div>
              <div className="kv"><span>Available</span><span>{fmtUsd(b.limit_cents - b.spent_cents - b.reserved_cents)}</span></div>
            </>
          ) : <p className="muted">loading…</p>}
        </div>

        <div className="card">
          <div className="step">Runway</div>
          {runway.data ? (
            <>
              <div className="kv"><span>Projected days</span><span>
                {runway.data.projected_days_remaining != null ? runway.data.projected_days_remaining.toFixed(1) : "—"}
              </span></div>
              <div className="kv"><span>Burn / day</span><span>{fmtUsd(runway.data.burn_rate_cents_per_day)}</span></div>
              <div className="kv"><span>Balance</span><span>{fmtUsd(runway.data.balance_cents)}</span></div>
              <button style={{ marginTop: 12 }} onClick={() => api.recomputeRunway(id).then(() => runway.reload())}>
                Recompute
              </button>
            </>
          ) : <p className="muted">loading…</p>}
        </div>
      </div>

      <div className="card">
        <div className="step">By category</div>
        {budget.data && Object.keys(budget.data.by_category).length > 0 ? (
          Object.entries(budget.data.by_category).map(([k, v]) => (
            <div key={k} className="kv"><span>{k}</span><span>{fmtUsd(v)}</span></div>
          ))
        ) : <p className="muted">No spend recorded yet.</p>}
      </div>

      <div className="card">
        <div className="step">By agent</div>
        {budget.data && Object.keys(budget.data.by_agent).length > 0 ? (
          Object.entries(budget.data.by_agent).map(([k, v]) => (
            <div key={k} className="kv"><span className="muted" style={{ fontSize: 12 }}>{k.slice(0, 8)}</span><span>{fmtUsd(v)}</span></div>
          ))
        ) : <p className="muted">No agent spend yet.</p>}
      </div>
    </div>
  );
}
