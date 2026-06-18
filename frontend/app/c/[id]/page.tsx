"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { api, fmtUsd, sortTasksForView, statusLabel, type Task } from "@/lib/api";
import { usePoll } from "@/lib/useApi";
import { Markdown } from "@/lib/markdown";

interface EventFrame {
  tasks: Task[];
  budget: { spent_cents: number; reserved_cents: number; limit_cents: number } | null;
}

export default function Overview() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const company = usePoll(() => api.company(id), 0, [id]);
  const budget = usePoll(() => api.budget(id), 5000, [id]);
  const decisions = usePoll(() => api.decisions(id, true), 5000, [id]);
  const digest = usePoll(() => api.digestLatest(id), 0, [id]);
  // TEMP dev tools — remove before launch.
  const dev = usePoll(() => api.devStatus(), 0, [id]);

  // Live task stream (SSE) so the founder sees work happening, auto-updating
  // without a refresh. Falls back to polling the task list so the Overview always
  // shows the task list (the same view as right after onboarding), even when the
  // org is idle and no SSE frames are arriving.
  const [liveTasks, setLiveTasks] = useState<Task[] | null>(null);
  const polledTasks = usePoll(() => api.tasks(id), 5000, [id]);
  const [justLaunched, setJustLaunched] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setJustLaunched(new URLSearchParams(window.location.search).get("launched") === "1");
    }
    const url = api.eventsUrl(id);
    if (typeof window === "undefined" || typeof EventSource === "undefined" || !url) return;
    const es = new EventSource(url);
    es.onmessage = (e: MessageEvent) => {
      try { setLiveTasks((JSON.parse(e.data) as EventFrame).tasks); } catch { /* ignore */ }
    };
    es.onerror = () => es.close();
    return () => es.close();
  }, [id]);

  const b = budget.data?.budget;
  const pct = b && b.limit_cents ? Math.min(100, (b.spent_cents / b.limit_cents) * 100) : 0;

  const tasks = liveTasks ?? polledTasks.data ?? [];
  const counts = tasks.reduce<Record<string, number>>((acc, t) => {
    acc[t.status] = (acc[t.status] ?? 0) + 1;
    return acc;
  }, {});
  const inFlight = (counts["running"] ?? 0) + (counts["queued"] ?? 0);
  // Decisions awaiting the founder float to the top, done tasks sink to the bottom.
  const recent = sortTasksForView(tasks).slice(0, 6);

  const deleteCompany = async () => {
    if (!window.confirm(
      "Delete this company and ALL its data (agents, tasks, budget, history)? " +
      "This stops it running and cannot be undone."
    )) return;
    setDeleting(true);
    try {
      await api.deleteCompany(id);
      router.push("/");
    } catch (e) {
      alert(String(e instanceof Error ? e.message : e));
      setDeleting(false);
    }
  };

  // TEMP dev tool — remove before launch. Wipes every account except the default.
  const deleteOtherAccounts = async () => {
    if (!window.confirm("DELETE ALL OTHER ACCOUNTS (everyone except the default dev account) and all their data? This cannot be undone.")) return;
    try {
      const res = await api.deleteOtherAccounts();
      alert(`Deleted ${res.deleted_accounts} account(s). The default account is preserved.`);
    } catch (e) {
      alert(String(e instanceof Error ? e.message : e));
    }
  };

  return (
    <div>
      <h2>{company.data?.name ?? "Company"}</h2>
      <p className="muted">
        Status: <span className={`status ${company.data?.status}`}>{company.data?.status ?? "—"}</span>
      </p>

      <div className="card">
        <div className="step" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {inFlight > 0 && <span className="spinner" style={{ width: 14, height: 14 }} />}
          <span>
            {justLaunched && inFlight > 0
              ? "🚀 Launched — initial work in progress"
              : inFlight > 0
                ? "Live activity"
                : "Tasks"}
          </span>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <span className="pill">{counts["running"] ?? 0} running</span>
          <span className="pill">{counts["queued"] ?? 0} queued</span>
          <span className="pill">{counts["done"] ?? 0} done</span>
          {(counts["waiting_approval"] ?? 0) > 0 && (
            <span className="pill">{counts["waiting_approval"]} awaiting you</span>
          )}
        </div>
        {recent.length > 0 ? (
          <div style={{ marginTop: 12 }}>
            {recent.map((t) => (
              <Link key={t.id} href={`/c/${id}/tasks?task=${t.id}`} className="actrow">
                <span className="goal">{"— ".repeat(t.depth)}{t.goal}</span>
                <span className={`status ${t.status}`}>{statusLabel(t.status)}</span>
              </Link>
            ))}
          </div>
        ) : (
          <p className="muted" style={{ marginTop: 10 }}>
            {inFlight > 0 ? "Agents are kicking off the first initiatives…" : "No tasks yet."}
          </p>
        )}
        <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>
          This updates live — tap a task for details. Open the Tasks tab for the full tree.
        </p>
      </div>

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
        <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>Latest digest{digest.data?.period_date ? ` · ${digest.data.period_date}` : ""}</span>
          <button className="ghost" style={{ marginTop: 0, padding: "6px 12px", fontSize: 12 }}
            onClick={() => api.generateDigest(id).then(() => digest.reload())}>
            Refresh
          </button>
        </div>
        {digest.data?.summary_md ? (
          <Markdown className="digest-md">{digest.data.summary_md}</Markdown>
        ) : (
          <div className="empty">Preparing your first digest…</div>
        )}
      </div>

      <div className="card danger-zone">
        <div className="step">Danger zone</div>
        <p className="muted">
          Permanently delete this company and stop all of its agents. This removes every
          task, budget record, and memory — there is no undo.
        </p>
        <button className="ghost danger" disabled={deleting} onClick={deleteCompany}>
          {deleting ? "Deleting…" : "Delete company"}
        </button>

        {/* TEMP DEV TOOL — remove before launch (backend app/api/dev.py + ABOS_DEV_TOOLS_ENABLED). */}
        {dev.data?.enabled && (
          <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px dashed var(--border)" }}>
            <p className="muted" style={{ fontSize: 12, margin: "0 0 8px" }}>
              ⚠️ Dev only — deletes every account except the default one. Remove before going live.
            </p>
            <button className="ghost danger" onClick={deleteOtherAccounts}>
              Delete all other accounts
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
