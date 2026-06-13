"use client";

import { useParams } from "next/navigation";
import { api, fmtUsd } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

export default function TasksPage() {
  const { id } = useParams<{ id: string }>();
  const tasks = usePoll(() => api.tasks(id), 3000, [id]);

  return (
    <div>
      <h2>Tasks <span className="muted" style={{ fontSize: 14 }}>(live)</span></h2>
      <div className="card" style={{ padding: 0 }}>
        <table>
          <thead>
            <tr><th>Goal</th><th>Depth</th><th>Cost</th><th>Status</th></tr>
          </thead>
          <tbody>
            {(tasks.data ?? []).map((t) => (
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
      {(tasks.data?.length ?? 0) === 0 && <div className="empty">Agents are warming up…</div>}
    </div>
  );
}
