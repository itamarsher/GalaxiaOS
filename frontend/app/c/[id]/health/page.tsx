"use client";

// The function-health board (RFC 0002): per-function KPI status vs. target, plus
// the agent-based KPIs. Read-only — GalaxiaOS's improvement cycle acts on this same
// status; here the founder just sees it at a glance.

import { useParams } from "next/navigation";
import { api, type AgentKpi, type HealthKpi } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

const STATUS = {
  on_track: { label: "on track", color: "var(--good)" },
  off_target: { label: "off target", color: "var(--danger)" },
  unmeasured: { label: "unmeasured", color: "var(--warn)" },
} as const;

function fmt(value: number | null, unit: string | null): string {
  if (value == null) return "—";
  if (unit === "ratio") return `${(value * 100).toFixed(1)}%`;
  const n = Math.abs(value) >= 100 ? Math.round(value) : Math.round(value * 100) / 100;
  return unit && unit !== "score" ? `${n} ${unit}` : `${n}`;
}

function KpiRow({ kpi }: { kpi: HealthKpi }) {
  const s = STATUS[kpi.status];
  return (
    <div className="kv">
      <span>{kpi.metric}</span>
      <span style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <span className="muted">
          {fmt(kpi.current, kpi.unit)}
          {kpi.target != null && <> / target {fmt(kpi.target, kpi.unit)}</>}
        </span>
        <span
          className="pill"
          style={{ color: s.color, borderColor: `color-mix(in srgb, ${s.color} 45%, transparent)` }}
        >
          {s.label}
        </span>
      </span>
    </div>
  );
}

export default function Health() {
  const { id } = useParams<{ id: string }>();
  const board = usePoll(() => api.functionHealth(id), 15000, [id]);

  const functions = board.data?.functions ?? [];
  const agentKpis: AgentKpi[] = board.data?.agent_kpis ?? [];

  return (
    <div>
      <h1>Function health</h1>
      <p className="sub">
        How each function you run is doing against its KPIs. GalaxiaOS continuously
        assesses this and drives the next improvement — instrumenting what isn&apos;t
        measured, and closing gaps on what&apos;s off target.
      </p>

      {board.loading && !board.data && <p className="muted">Loading…</p>}
      {!board.loading && functions.length === 0 && agentKpis.length === 0 && (
        <div className="card">
          <p className="muted">
            No health KPIs yet. Pick functions at onboarding (or in Settings) and
            GalaxiaOS seeds each one&apos;s targets here.
          </p>
        </div>
      )}

      {functions.map((f) => (
        <div key={f.function} className="card">
          <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>{f.title}</span>
            <span
              className="pill"
              style={{
                color: f.on_track ? "var(--good)" : "var(--warn)",
                borderColor: `color-mix(in srgb, ${f.on_track ? "var(--good)" : "var(--warn)"} 45%, transparent)`,
              }}
            >
              {f.on_track ? "healthy" : "needs attention"}
            </span>
          </div>
          {f.kpis.length === 0
            ? <p className="muted" style={{ fontSize: 13 }}>No KPIs defined.</p>
            : f.kpis.map((k) => <KpiRow key={k.metric} kpi={k} />)}
        </div>
      ))}

      {agentKpis.length > 0 && (
        <div className="card">
          <div className="step">Agent health · Are the agents running your functions dependable?</div>
          {agentKpis.map((k) => (
            <KpiRow
              key={k.metric}
              kpi={{ ...k, status: k.current == null ? "unmeasured" : "on_track" }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
