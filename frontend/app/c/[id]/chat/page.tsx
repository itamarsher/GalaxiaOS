"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { api, decisionKindLabel, type ChatChannel, type ChatMessage } from "@/lib/api";
import { usePoll } from "@/lib/useApi";
import { Markdown } from "@/lib/markdown";

// The unified collaboration surface. Agents and the founder talk in channels and
// 1:1 threads; what used to be the "decision inbox" is now just founder DMs marked
// "waiting for a response" (open-ended asks resolve by replying; structured ones —
// budget/plan/hire/external — show inline Approve/Reject).
export default function ChatPage() {
  const { id } = useParams<{ id: string }>();
  const search = useSearchParams();
  const fromUrl = search.get("channel");
  const channels = usePoll(() => api.chatChannels(id), 5000, [id]);
  const list = channels.data ?? [];
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  // A channel picked from the sidebar (?channel=) wins; otherwise default to the
  // first thread that needs the founder, else the most recent.
  useEffect(() => {
    if (fromUrl) {
      setSelected(fromUrl);
      return;
    }
    if (selected || list.length === 0) return;
    const needy = list.find((c) => isWaiting(c));
    setSelected((needy ?? list[0]).id);
  }, [fromUrl, list, selected]);

  const active = useMemo(() => list.find((c) => c.id === selected) ?? null, [list, selected]);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2>Chat</h2>
        <button style={{ marginTop: 0 }} onClick={() => setCreating((v) => !v)}>
          {creating ? "Cancel" : "New channel"}
        </button>
      </div>
      <p className="muted">
        Talk to your fleet. Threads marked <span className="status pending">waiting</span> need a
        reply from you — answer to unblock the agent (or Approve/Reject a request).
      </p>

      {creating && <NewChannel companyId={id} onDone={() => { setCreating(false); channels.reload(); }} />}

      {list.length === 0 && !creating && (
        <div className="empty">No conversations yet. Agents will reach out here when they need you.</div>
      )}

      {/* Pick a conversation from the left rail; this pane shows the thread. */}
      {active ? (
        <Thread companyId={id} channel={active} onChanged={() => channels.reload()} />
      ) : (
        list.length > 0 && (
          <div className="empty">Pick a conversation from the sidebar to open it.</div>
        )
      )}
    </div>
  );
}

function isWaiting(c: ChatChannel): boolean {
  return c.waiting_agents.length > 0 || c.pending_decision != null;
}

function channelTitle(c: ChatChannel): string {
  return c.kind === "direct" ? c.name : `#${c.name}`;
}

function Thread({
  companyId,
  channel,
  onChanged,
}: {
  companyId: string;
  channel: ChatChannel;
  onChanged: () => void;
}) {
  const messages = usePoll(() => api.chatMessages(companyId, channel.id), 4000, [channel.id]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const msgs = messages.data ?? [];
  const decision = channel.pending_decision;

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    try {
      await api.postChatMessage(companyId, channel.id, text);
      messages.reload();
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const resolve = async (approve: boolean) => {
    if (!decision) return;
    setBusy(true);
    try {
      const note = input.trim() || undefined;
      if (approve) await api.approveDecision(decision.id, note);
      else await api.rejectDecision(decision.id, note);
      setInput("");
      messages.reload();
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ marginTop: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <strong>{channelTitle(channel)}</strong>
        <span className="muted" style={{ fontSize: 12 }}>
          {channel.participants.map((p) => p.role ?? p.name).join(", ")}
        </span>
      </div>
      {channel.purpose && (
        <p className="muted" style={{ marginTop: 4 }}>{channel.purpose}</p>
      )}

      <div className="chat" style={{ margin: "12px 0", maxHeight: 420, overflowY: "auto" }}>
        {msgs.length === 0 && <div className="msg bot muted">No messages yet.</div>}
        {msgs.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {busy && <div className="msg bot muted">sending…</div>}
      </div>

      {decision && (
        <div className="dctx" style={{ marginBottom: 12 }}>
          <div className="row">
            <span className="lbl">Awaiting</span>
            <span className="val accent">{decisionKindLabel(decision.kind)}</span>
          </div>
          <p className="muted" style={{ marginTop: 6 }}>
            Approve or reject below. You can add a note (used as your guidance to the agent).
          </p>
        </div>
      )}

      <div className="chatbar">
        <input
          placeholder={decision ? "Add a note (optional), then Approve/Reject…" : "Reply…"}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !decision && send()}
          disabled={busy}
        />
        {decision ? (
          <>
            <button onClick={() => resolve(true)} disabled={busy}>Approve</button>
            <button className="ghost" onClick={() => resolve(false)} disabled={busy}>Reject</button>
          </>
        ) : (
          <button onClick={send} disabled={busy || !input.trim()}>Send</button>
        )}
      </div>
    </div>
  );
}

function MessageBubble({ message: m }: { message: ChatMessage }) {
  const who = m.is_founder ? "you" : "bot";
  const label = m.is_founder
    ? "You"
    : `${m.sender_name ?? "Agent"}${m.sender_role ? ` · ${m.sender_role}` : ""}`;
  return (
    <div className={`msg ${who}`}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 2 }}>{label}</div>
      <Markdown>{m.body}</Markdown>
    </div>
  );
}

function NewChannel({ companyId, onDone }: { companyId: string; onDone: () => void }) {
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [roles, setRoles] = useState("");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      await api.createChatChannel(companyId, {
        name: name.trim(),
        purpose: purpose.trim() || undefined,
        member_roles: roles.split(",").map((r) => r.trim()).filter(Boolean),
      });
      onDone();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <label>Channel name</label>
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="q3-launch" />
      <label>Purpose</label>
      <input value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="Coordinate the launch" />
      <label>Member roles (comma-separated)</label>
      <input value={roles} onChange={(e) => setRoles(e.target.value)} placeholder="growth, research, finance" />
      <div className="btnrow" style={{ marginTop: 12 }}>
        <button onClick={create} disabled={busy || !name.trim()}>Create channel</button>
      </div>
    </div>
  );
}
