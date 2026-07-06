"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { api, type Memory } from "@/lib/api";

export default function MemoryPage() {
  const { id } = useParams<{ id: string }>();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Memory[]>([]);
  const [loaded, setLoaded] = useState(false);

  const load = async (query?: string) => {
    setItems(await api.memory(id, query || undefined));
    setLoaded(true);
  };

  const remove = async (m: Memory) => {
    if (!window.confirm(`Forget this memory?\n\n${m.title}`)) return;
    await api.deleteMemory(id, m.id);
    setItems((cur) => cur.filter((x) => x.id !== m.id));
  };

  return (
    <div>
      <h2>Company Memory</h2>
      <p className="muted">
        The company brain — decisions, experiments, results, and learnings. Search ranks by
        similarity and recency (the same recall the agents use); leave it blank for the most recent.
      </p>
      <div className="chatbar">
        <input
          placeholder="Search memory (e.g. customer acquisition)…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(q)}
        />
        <button onClick={() => load(q)}>Search</button>
      </div>
      {loaded && items.length === 0 && <div className="empty">No memory entries yet.</div>}
      {items.map((m) => (
        <div key={m.id} className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span className="pill">{m.type}</span>
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <span className="muted" style={{ fontSize: 12 }}>{new Date(m.created_at).toLocaleString()}</span>
              <button className="ghost danger" style={{ marginTop: 0 }} onClick={() => remove(m)}>Forget</button>
            </div>
          </div>
          <strong style={{ display: "block", margin: "8px 0 4px" }}>{m.title}</strong>
          <span className="muted">{m.content}</span>
        </div>
      ))}
    </div>
  );
}
