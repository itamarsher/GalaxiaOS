"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, fmtUsd, statusLabel, type Task, type TaskDetail } from "@/lib/api";
import { usePoll } from "@/lib/useApi";
import { Markdown } from "@/lib/markdown";

interface EventFrame {
  tasks: Task[];
  budget: { spent_cents: number; reserved_cents: number; limit_cents: number } | null;
}

export default function TasksPage() {
  const { id } = useParams<{ id: string }>();
  // Streamed tasks via SSE; null until the first frame arrives (or SSE fails).
  const [streamed, setStreamed] = useState<Task[] | null>(null);
  const [sseOk, setSseOk] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);
  // Fallback polling, only active once SSE has errored out.
  const polled = usePoll(() => api.tasks(id), sseOk ? 0 : 3000, [id, sseOk]);

  // Deep-link: /tasks?task=<id> (e.g. from the Overview activity feed) opens the drawer.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const t = new URLSearchParams(window.location.search).get("task");
    if (t) setOpenId(t);
  }, []);

  useEffect(() => {
    const url = api.eventsUrl(id);
    if (typeof window === "undefined" || typeof EventSource === "undefined" || !url) {
      setSseOk(false);
      return;
    }
    const es = new EventSource(url);
    es.onmessage = (e: MessageEvent) => {
      try {
        const frame = JSON.parse(e.data) as EventFrame;
        setStreamed(frame.tasks);
        setSseOk(true);
      } catch {
        /* ignore malformed frame */
      }
    };
    es.onerror = () => {
      es.close();
      setSseOk(false);
    };
    return () => es.close();
  }, [id]);

  const tasks: Task[] = streamed ?? polled.data ?? [];

  return (
    <div>
      <h2>Tasks <span className="muted" style={{ fontSize: 14 }}>(live)</span></h2>
      <p className="muted">Select a task to see its execution and result.</p>
      <div className="card" style={{ padding: 0 }}>
        <table>
          <thead>
            <tr><th>Goal</th><th>Depth</th><th>Cost</th><th>Status</th></tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t.id} className="clickable" onClick={() => setOpenId(t.id)}>
                <td>{"— ".repeat(t.depth)}{t.goal.slice(0, 90)}</td>
                <td>{t.depth}</td>
                <td>{fmtUsd(t.cost_cents)}</td>
                <td><span className={`status ${t.status}`}>{statusLabel(t.status)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {tasks.length === 0 && <div className="empty">Agents are warming up…</div>}

      {openId && <TaskDrawer companyId={id} taskId={openId} onClose={() => setOpenId(null)} />}
    </div>
  );
}

function TaskDrawer({ companyId, taskId, onClose }: { companyId: string; taskId: string; onClose: () => void }) {
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    api.task(companyId, taskId)
      .then((t) => setTask(t))
      .catch((e) => setErr(String(e instanceof Error ? e.message : e)));
  };

  useEffect(() => {
    setTask(null); setErr(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, taskId]);

  const resolve = async (approve: boolean) => {
    const d = task?.pending_decision;
    if (!d) return;
    setBusy(true);
    try {
      if (approve) await api.approveDecision(d.id);
      else await api.rejectDecision(d.id);
      load();
    } finally {
      setBusy(false);
    }
  };

  // Pull a readable execution summary + result out of the (free-form) output blob.
  const out = task?.output ?? null;
  const summary = out && typeof out.summary === "string" ? out.summary : null;
  const result = out
    ? (typeof out.result === "string" ? out.result : JSON.stringify(out, null, 2))
    : null;

  return (
    <div className="drawer-scrim" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <h3 style={{ margin: 0 }}>Task detail</h3>
          <button className="ghost" style={{ marginTop: 0 }} onClick={onClose}>Close</button>
        </div>

        {err && <div className="err">{err}</div>}
        {!task && !err && <p className="muted">Loading…</p>}

        {task && (
          <>
            <p style={{ margin: "12px 0 4px" }}>{task.goal}</p>
            <div className="kv"><span>Status</span><span className={`status ${task.status}`}>{statusLabel(task.status)}</span></div>

            {task.pending_decision && (
              <div className="card" style={{ borderColor: "var(--warn)", marginTop: 12 }}>
                <div className="step" style={{ color: "var(--warn)" }}>⏳ Waiting for your decision</div>
                <Markdown>{task.pending_decision.summary}</Markdown>
                <div className="btnrow">
                  <button disabled={busy} onClick={() => resolve(true)}>Approve</button>
                  <button className="ghost" disabled={busy} onClick={() => resolve(false)}>Reject</button>
                  <a className="muted" style={{ fontSize: 12, alignSelf: "center" }}
                     href={`/c/${companyId}/decisions`}>Discuss in Decisions →</a>
                </div>
              </div>
            )}
            <div className="kv"><span>Agent</span><span>{task.agent_name ?? "—"}{task.agent_role ? ` · ${task.agent_role}` : ""}</span></div>
            <div className="kv"><span>Depth</span><span>{task.depth}</span></div>
            <div className="kv"><span>Cost</span><span>{fmtUsd(task.cost_cents)}</span></div>
            <div className="kv"><span>Started</span><span>{new Date(task.created_at).toLocaleString()}</span></div>

            <h4>Execution summary</h4>
            {summary ? <p style={{ margin: 0 }}>{summary}</p>
              : <p className="muted" style={{ margin: 0 }}>No summary yet — this task is still in progress.</p>}

            <h4>Result</h4>
            {result ? <pre>{result}</pre>
              : <p className="muted" style={{ margin: 0 }}>No result recorded yet.</p>}

            {task.children.length > 0 && (
              <>
                <h4>Dispatched sub-tasks ({task.children.length})</h4>
                {task.children.map((c) => (
                  <div key={c.id} className="kv">
                    <span>{c.goal.slice(0, 60)}</span>
                    <span className={`status ${c.status}`}>{c.status}</span>
                  </div>
                ))}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
