"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { api, type Memory } from "@/lib/api";

export default function MemoryPage() {
  const { id } = useParams<{ id: string }>();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Memory[]>([]);
  const [loaded, setLoaded] = useState(false);

  const search = async () => {
    setItems(await api.memory(id, q || undefined));
    setLoaded(true);
  };

  return (
    <div>
      <h2>Company Memory</h2>
      <p className="muted">The company brain — decisions, experiments, results, and learnings (semantic search).</p>
      <div className="chatbar">
        <input
          placeholder="Search memory (e.g. customer acquisition)…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()}
        />
        <button onClick={search}>Search</button>
      </div>
      {loaded && items.length === 0 && <div className="empty">No memory entries yet.</div>}
      {items.map((m) => (
        <div key={m.id} className="card">
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span className="pill">{m.type}</span>
            <span className="muted" style={{ fontSize: 12 }}>{new Date(m.created_at).toLocaleString()}</span>
          </div>
          <strong style={{ display: "block", margin: "8px 0 4px" }}>{m.title}</strong>
          <span className="muted">{m.content}</span>
        </div>
      ))}
    </div>
  );
}
