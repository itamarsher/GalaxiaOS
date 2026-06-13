"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, fmtUsd, type Task } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

interface EventFrame {
  tasks: Task[];
  budget: { spent_cents: number; reserved_cents: number; limit_cents: number } | null;
}

export default function TasksPage() {
  const { id } = useParams<{ id: string }>();
  // Streamed tasks via SSE; null until the first frame arrives (or SSE fails).
  const [streamed, setStreamed] = useState<Task[] | null>(null);
  const [sseOk, setSseOk] = useState(true);
  // Fallback polling, only active once SSE has errored out.
  const polled = usePoll(() => api.tasks(id), sseOk ? 0 : 3000, [id, sseOk]);

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
      <div className="card" style={{ padding: 0 }}>
        <table>
          <thead>
            <tr><th>Goal</th><th>Depth</th><th>Cost</th><th>Status</th></tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t.id}>
                <td>{"— ".repeat(t.depth)}{t.goal.slice(0, 90)}</td>
                <td>{t.depth}</td>
                <td>{fmtUsd(t.cost_cents)}</td>
                <td><span className={`status ${t.status}`}>{t.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {tasks.length === 0 && <div className="empty">Agents are warming up…</div>}
    </div>
  );
}
