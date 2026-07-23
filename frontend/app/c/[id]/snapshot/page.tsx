"use client";

// The agent-first "snapshot" surface: a single read-only view of a company's
// state for a human who only checks in. Agents do the work; this page never
// mutates anything — it composes existing read endpoints into one glance:
// status, objectives, the live fleet, budget/runway, what's awaiting the founder,
// recent activity, and shipped sites.

import { useParams } from "next/navigation";
import { api, fmtUsd, statusLabel, type Task } from "@/lib/api";
import { usePoll, useLiveTasks } from "@/lib/useApi";

const ACTIVE = new Set(["queued", "running", "waiting_approval", "auditing"]);

function ago(ts: string): string {
  const secs = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

export default function Snapshot() {
  const { id } = useParams<{ id: string }>();
  const company = usePoll(() => api.company(id), 0, [id]);
  const objectives = usePoll(() => api.objectives(id), 10000, [id]);
  const org = usePoll(() => api.org(id), 10000, [id]);
  const budget = usePoll(() => api.budget(id), 5000, [id]);
  const runway = usePoll(() => api.runway(id), 15000, [id]);
  const cycle = usePoll(() => api.cycleStatus(id), 5000, [id]);
  const decisions = usePoll(() => api.decisions(id, true), 5000, [id]);
  const sites = usePoll(() => api.sites(id), 15000, [id]);
  const missionLog = usePoll(() => api.missionLog(id), 5000, [id]);
  const tasks = useLiveTasks(id);

  const b = budget.data?.budget;
  const pct = b && b.limit_cents ? Math.min(100, (b.spent_cents / b.limit_cents) * 100) : 0;
  const agents = org.data?.agents ?? [];
  const pending = decisions.data ?? [];
  const log = missionLog.data?.mission_log ?? [];
  const active = tasks.filter((t: Task) => ACTIVE.has(t.status));
  const liveSites = (sites.data ?? []).filter((s) => s.status === "published");
  const cyc = cycle.data;

  return (
    <div>
      <h1>{company.data?.name ?? "Company"}</h1>
      <p className="sub">
        <span className="pill">{statusLabel(company.data?.status ?? "")}</span>{" "}
        {cyc?.active
          ? `Working — ${cyc.active_task_count} task${cyc.active_task_count === 1 ? "" : "s"} in flight`
          : "Idle"}
      </p>

      {pending.length > 0 && (
        <div className="card" style={{ borderColor: "var(--accent)" }}>
          <div className="step">Awaiting you ({pending.length})</div>
          {pending.map((d) => (
            <div key={d.id} className="kv">
              <span>
                <strong>{statusLabel(d.kind)}</strong>
                {d.agent_role ? <span className="muted"> · {d.agent_role}</span> : null}
                <br />
                <span className="muted" style={{ fontSize: 13 }}>
                  {(d.summary ?? "").slice(0, 160)}
                </span>
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="row">
        <div className="card" style={{ flex: "1 1 240px" }}>
          <div className="step">Budget</div>
          <div className="kv">
            <span className="muted">Spent</span>
            <span>
              {fmtUsd(b?.spent_cents)} / {fmtUsd(b?.limit_cents)}
            </span>
          </div>
          <div
            style={{
              height: 8,
              background: "var(--panel-2)",
              borderRadius: 999,
              overflow: "hidden",
              margin: "6px 0",
            }}
          >
            <div style={{ width: `${pct}%`, height: "100%", background: "var(--accent)" }} />
          </div>
          <div className="kv">
            <span className="muted">Runway</span>
            <span>
              {runway.data?.projected_days_remaining != null
                ? `${runway.data.projected_days_remaining} days`
                : "—"}
            </span>
          </div>
        </div>

        <div className="card" style={{ flex: "1 1 240px" }}>
          <div className="step">Objectives</div>
          {(objectives.data ?? []).length === 0 ? (
            <p className="muted">None yet.</p>
          ) : (
            (objectives.data ?? []).map((o) => (
              <div key={o.id} className="kv">
                <span>{o.title}</span>
                <span className="pill">{statusLabel(o.status)}</span>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="card">
        <div className="step">Fleet ({agents.length})</div>
        <div className="row">
          {agents.map((a) => (
            <div key={a.id} className="agent" style={{ flex: "1 1 200px" }}>
              <span className="role">{a.role}</span>
              <div>{a.name}</div>
              <span className="pill">{statusLabel(a.status)}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="step">Recent activity</div>
        {log.length === 0 && active.length === 0 ? (
          <p className="muted">Nothing yet.</p>
        ) : (
          <>
            {log.slice(0, 6).map((e) => (
              <div key={e.id} className="kv">
                <span>
                  {e.headline}
                  <span className="muted"> · {e.agent_name}</span>
                </span>
                <span className="muted" style={{ fontSize: 12 }}>
                  {ago(e.ts)}
                </span>
              </div>
            ))}
            {active.slice(0, 6).map((t) => (
              <div key={t.id} className="kv">
                <span className="muted">{t.goal.slice(0, 80)}</span>
                <span className="pill">{statusLabel(t.status)}</span>
              </div>
            ))}
          </>
        )}
      </div>

      {liveSites.length > 0 && (
        <div className="card">
          <div className="step">Live sites</div>
          {liveSites.map((s) => (
            <div key={s.id} className="kv">
              <span>
                {s.deployment_url ? (
                  <a href={s.deployment_url} target="_blank" rel="noopener noreferrer">
                    {s.title}
                  </a>
                ) : (
                  s.title
                )}
              </span>
              <span className="muted" style={{ fontSize: 12 }}>
                {s.lead_count} lead{s.lead_count === 1 ? "" : "s"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
