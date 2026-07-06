"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";

interface Turn { who: "user" | "bot"; text: string; kind?: string }

const SUGGESTIONS = [
  "Why is most of our budget being spent?",
  "What are our most expensive initiatives?",
  "Pause all experiments with ROI below 5%",
];

export default function CopilotPage() {
  const { id } = useParams<{ id: string }>();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  const send = async (text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    setInput("");
    setTurns((t) => [...t, { who: "user", text: q }]);
    setBusy(true);
    try {
      const res = await api.copilotAsk(id, q);
      setTurns((t) => [...t, { who: "bot", text: res.answer, kind: res.kind }]);
    } catch (e) {
      setTurns((t) => [...t, { who: "bot", text: String(e instanceof Error ? e.message : e) }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h2>Founder Copilot</h2>
      <p className="muted">Ask about the company, or issue a command. Commands run as allow-listed, code-executed actions.</p>

      <div className="card">
        {turns.length === 0 ? (
          <div className="empty">
            Try:
            <div style={{ marginTop: 10 }}>
              {SUGGESTIONS.map((s) => (
                <button key={s} className="ghost" style={{ marginTop: 6, marginRight: 6 }} onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="chat">
            {turns.map((t, i) => (
              <div key={i} className={`msg ${t.who}`}>
                {t.kind === "command" && <div className="pill" style={{ marginBottom: 6 }}>command</div>}
                {t.text}
              </div>
            ))}
            {busy && <div className="msg bot muted">thinking…</div>}
          </div>
        )}

        <div className="chatbar">
          <input
            placeholder="Ask or command…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send(input)}
            disabled={busy}
          />
          <button onClick={() => send(input)} disabled={busy}>Send</button>
        </div>
      </div>
    </div>
  );
}
