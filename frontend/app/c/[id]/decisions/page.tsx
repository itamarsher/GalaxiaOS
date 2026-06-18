"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, decisionKindLabel, type ChatTurn, type Decision } from "@/lib/api";
import { usePoll } from "@/lib/useApi";
import { Markdown } from "@/lib/markdown";

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
  const [chat, setChat] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);

  const act = async (approve: boolean) => {
    setBusy(true);
    try {
      // The conversation IS the guidance: it's persisted server-side and applied
      // with the verdict, so no separate note is sent.
      if (approve) await api.approveDecision(d.id);
      else await api.rejectDecision(d.id);
      onResolved();
    } finally {
      setBusy(false);
    }
  };

  // The thread is persisted server-side; load it on mount so it survives reloads
  // and is shared across devices.
  useEffect(() => {
    let active = true;
    api.decisionChatThread(d.id)
      .then((res) => { if (active) setChat(res.thread); })
      .catch(() => { /* keep whatever is on screen */ });
    return () => { active = false; };
  }, [d.id]);

  const send = async () => {
    const q = input.trim();
    if (!q || thinking) return;
    setInput("");
    setChat((c) => [...c, { who: "you", text: q }]); // optimistic
    setThinking(true);
    try {
      const res = await api.decisionChat(d.id, q);
      setChat(res.thread); // server is the source of truth
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

      {/* The discussion is the only guidance channel: talk it through with the
          agent, then give your verdict below. The whole conversation is what the
          agent acts on. */}
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
            placeholder="Ask the agent why, or tell it how to change this…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            disabled={thinking}
          />
          <button onClick={send} disabled={thinking || !input.trim()}>Send</button>
        </div>

        <div className="btnrow" style={{ marginTop: 12 }}>
          <button disabled={busy} onClick={() => act(true)}>Approve</button>
          <button className="ghost" disabled={busy} onClick={() => act(false)}>Reject</button>
        </div>
      </div>
    </div>
  );
}
