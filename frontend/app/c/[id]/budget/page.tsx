"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { api, fmtUsd, type AgentSpend } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

export default function BudgetPage() {
  const { id } = useParams<{ id: string }>();
  const budget = usePoll(() => api.budget(id), 4000, [id]);
  const runway = usePoll(() => api.runway(id), 4000, [id]);
  const byAgent = usePoll(() => api.budgetByAgent(id), 4000, [id]);

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
        {byAgent.data && byAgent.data.length > 0 ? (
          byAgent.data.map((a) => <AgentSpendRow key={a.agent_id ?? "none"} agent={a} />)
        ) : <p className="muted">No agent spend yet.</p>}
      </div>
    </div>
  );
}

function AgentSpendRow({ agent }: { agent: AgentSpend }) {
  const [open, setOpen] = useState(false);
  const label = agent.agent_name ?? (agent.agent_id ? `${agent.agent_id.slice(0, 8)}…` : "Platform / unattributed");

  return (
    <div>
      <div className={`exprow ${open ? "open" : ""}`} onClick={() => setOpen((o) => !o)}>
        <span style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span className="chev">▶</span>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {label}
            {agent.agent_role && <span className="muted" style={{ fontSize: 12 }}> · {agent.agent_role}</span>}
          </span>
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 8, flex: "0 0 auto" }}>
          <strong>{fmtUsd(agent.total_cents)}</strong>
          <span className="pill">{agent.entries.length}</span>
        </span>
      </div>
      {open && (
        <div className="expbody">
          {agent.entries.length === 0 ? (
            <p className="muted" style={{ fontSize: 13 }}>No itemized expenses.</p>
          ) : (
            agent.entries.map((e) => (
              <div key={e.id} className="line">
                <span style={{ minWidth: 0 }}>
                  <span className="pill" style={{ marginRight: 6 }}>{e.category}</span>
                  {e.description || e.vendor || e.sku || "—"}
                  <span className="muted" style={{ fontSize: 11, display: "block" }}>
                    {new Date(e.created_at).toLocaleString()}
                  </span>
                </span>
                <strong style={{ flex: "0 0 auto" }}>{fmtUsd(e.amount_cents)}</strong>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
