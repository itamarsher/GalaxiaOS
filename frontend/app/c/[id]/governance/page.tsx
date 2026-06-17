"use client";

import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

export default function GovernancePage() {
  const { id } = useParams<{ id: string }>();
  const policies = usePoll(() => api.policies(id), 0, [id]);
  const breakers = usePoll(() => api.breakers(id), 5000, [id]);
  const reputation = usePoll(() => api.reputation(id), 5000, [id]);

  return (
    <div>
      <h2>Governance</h2>

      <div className="card">
        <div className="step">Policy engine</div>
        <table>
          <thead><tr><th>Name</th><th>Effect</th><th>Priority</th><th>Rule</th></tr></thead>
          <tbody>
            {(policies.data ?? []).map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td><span className={`status ${p.effect === "deny" ? "failed" : p.effect === "require_approval" ? "waiting_approval" : "active"}`}>{p.effect}</span></td>
                <td>{p.priority}</td>
                <td className="muted" style={{ fontSize: 12 }}>{JSON.stringify(p.rule)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(policies.data?.length ?? 0) === 0 && <p className="muted">No policies.</p>}
      </div>

      <div className="card">
        <div className="step">Circuit breakers</div>
        <table>
          <thead><tr><th>Type</th><th>State</th><th>Reason</th><th></th></tr></thead>
          <tbody>
            {(breakers.data ?? []).map((b) => (
              <tr key={b.id}>
                <td>{b.type}</td>
                <td><span className={`status ${b.state}`}>{b.state}</span></td>
                <td className="muted">{b.tripped_reason ?? "—"}</td>
                <td>{b.state === "tripped" && (
                  <button className="ghost" style={{ marginTop: 0 }}
                    onClick={() => api.resetBreaker(id, b.id).then(() => breakers.reload())}>Reset</button>
                )}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(breakers.data?.length ?? 0) === 0 && <p className="muted">No breakers tripped.</p>}
      </div>

      <div className="card">
        <div className="step">Reputation</div>
        <table>
          <thead><tr><th>Agent</th><th>Trust</th><th>Accuracy</th><th>ROI</th><th>Reliability</th><th>n</th></tr></thead>
          <tbody>
            {(reputation.data ?? []).map((r) => (
              <tr key={r.agent_id}>
                <td>
                  <div>{r.agent_name ?? "Unknown agent"}</div>
                  <div className="muted" style={{ fontSize: 11 }}>
                    {r.agent_role ? `${r.agent_role} · ` : ""}{r.agent_id.slice(0, 8)}
                  </div>
                </td>
                <td>{(r.trust * 100).toFixed(0)}%</td>
                <td>{(r.accuracy * 100).toFixed(0)}%</td>
                <td>{(r.roi * 100).toFixed(0)}%</td>
                <td>{(r.reliability * 100).toFixed(0)}%</td>
                <td>{r.sample_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(reputation.data?.length ?? 0) === 0 && <p className="muted">No reputation data yet.</p>}
      </div>
    </div>
  );
}
