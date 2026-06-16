"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { api, decisionKindLabel, type Decision } from "@/lib/api";
import { usePoll } from "@/lib/useApi";
import { Markdown } from "@/lib/markdown";

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

  const raisedBy = d.agent_name
    ? `${d.agent_name}${d.agent_role ? ` · ${d.agent_role}` : ""}`
    : null;

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <span className="status pending">{decisionKindLabel(d.kind)}</span>
        <span className="muted" style={{ fontSize: 12 }}>{new Date(d.created_at).toLocaleString()}</span>
      </div>

      {/* Bigger picture first: what objective / initiative / agent this is about,
          so the founder has context before reading the specifics. */}
      <div className="dctx">
        {d.objective_title && (
          <div className="row">
            <span className="lbl">Objective</span>
            <span className="val accent">{d.objective_title}</span>
          </div>
        )}
        <div className="row">
          <span className="lbl">Triggered by</span>
          <span className="val">{d.task_goal ?? "—"}</span>
        </div>
        {d.initiative && d.initiative !== d.task_goal && (
          <div className="row">
            <span className="lbl">Initiative</span>
            <span className="val">{d.initiative}</span>
          </div>
        )}
        {raisedBy && (
          <div className="row">
            <span className="lbl">Raised by</span>
            <span className="val">{raisedBy}</span>
          </div>
        )}
      </div>

      <label style={{ marginTop: 0 }}>Details</label>
      <Markdown>{d.summary}</Markdown>

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
                <div key={i} className={`msg ${t.who === "you" ? "user" : "bot"}`}>
                  {t.who === "agent" ? <Markdown>{t.text}</Markdown> : t.text}
                </div>
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
