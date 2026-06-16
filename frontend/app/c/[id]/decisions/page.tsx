"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { api, statusLabel, type Decision } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

interface ChatTurn { who: "you" | "agent"; text: string }

export default function DecisionsPage() {
  const { id } = useParams<{ id: string }>();
  const decisions = usePoll(() => api.decisions(id, true), 5000, [id]);
  const list = decisions.data ?? [];

  return (
    <div>
      <h2>Decision inbox</h2>
      <p className="muted">Governance escalations and budget approvals that pause their task until you respond.</p>
      {list.length === 0 && <div className="empty">Nothing needs your approval. 🎉</div>}
      {list.map((d) => (
        <DecisionCard key={d.id} decision={d} onResolved={() => decisions.reload()} />
      ))}
    </div>
  );
}

function DecisionCard({ decision: d, onResolved }: { decision: Decision; onResolved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [showChat, setShowChat] = useState(false);
  const [chat, setChat] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);

  const act = async (approve: boolean) => {
    setBusy(true);
    try {
      if (approve) await api.approveDecision(d.id, note || undefined);
      else await api.rejectDecision(d.id, note || undefined);
      onResolved();
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    const q = input.trim();
    if (!q || thinking) return;
    setInput("");
    setChat((c) => [...c, { who: "you", text: q }]);
    setThinking(true);
    try {
      const res = await api.decisionChat(d.id, q);
      setChat((c) => [...c, { who: "agent", text: res.answer }]);
    } catch (e) {
      setChat((c) => [...c, { who: "agent", text: String(e instanceof Error ? e.message : e) }]);
    } finally {
      setThinking(false);
    }
  };

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <span className="status pending">{statusLabel(d.kind)}</span>
        <span className="muted" style={{ fontSize: 12 }}>{new Date(d.created_at).toLocaleString()}</span>
      </div>
      <p style={{ margin: "10px 0 4px" }}>{d.summary}</p>
      {d.agent_name && <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>Raised by {d.agent_name}</p>}

      <label>Guidance for the agent (optional — applied whether you approve or reject)</label>
      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="e.g. Go ahead, but cap the spend at $20 and use the .io domain."
        style={{ minHeight: 60 }}
      />

      <div className="btnrow">
        <button disabled={busy} onClick={() => act(true)}>Approve</button>
        <button className="ghost" disabled={busy} onClick={() => act(false)}>Reject</button>
        <button className="ghost" onClick={() => setShowChat((s) => !s)}>
          {showChat ? "Hide chat" : "💬 Discuss"}
        </button>
      </div>

      {showChat && (
        <div style={{ marginTop: 12 }}>
          {chat.length > 0 && (
            <div className="chat" style={{ marginBottom: 10 }}>
              {chat.map((t, i) => (
                <div key={i} className={`msg ${t.who === "you" ? "user" : "bot"}`}>{t.text}</div>
              ))}
              {thinking && <div className="msg bot muted">thinking…</div>}
            </div>
          )}
          <div className="chatbar">
            <input
              placeholder="Ask the agent why, or how to change this…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              disabled={thinking}
            />
            <button onClick={send} disabled={thinking || !input.trim()}>Send</button>
          </div>
        </div>
      )}
    </div>
  );
}
