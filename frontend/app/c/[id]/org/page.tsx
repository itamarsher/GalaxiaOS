"use client";

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
        <button className="ghost" style={{ marginTop: 10 }} onClick={() => toggle(a)}>
          {a.status === "paused" ? "Resume" : "Pause"}
        </button>
      </div>
    );
  };

  return (
    <div>
      <h2>Organization</h2>
      {ceo && <Card a={ceo} />}
      {others.length > 0 && <h3>Reports to {ceo?.name ?? "CEO"}</h3>}
      <div className="grid2">
        {others.map((a) => <Card key={a.id} a={a} />)}
      </div>
      {agents.length === 0 && <div className="empty">No agents yet.</div>}
    </div>
  );
}
