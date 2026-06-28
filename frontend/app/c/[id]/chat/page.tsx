"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import {
  api,
  decisionKindLabel,
  type ChatChannel,
  type ChatMessage,
  type ChatThread,
  type Decision,
} from "@/lib/api";
import { usePoll } from "@/lib/useApi";
import { Markdown } from "@/lib/markdown";
import { Avatar, channelDisplayName, founderIsMember, isCeoDm } from "@/lib/chat";

// The unified collaboration surface, laid out like Slack: a channel header, a
// linear message timeline (avatar · name · time · message), and a composer at
// the bottom. Agents and the founder talk in channels and 1:1 DMs; what used to
// be the "decision inbox" is now founder DMs marked "waiting for a response"
// (open-ended asks resolve by replying; structured ones — budget/plan/hire/
// external — show inline Approve/Reject). The founder sees every channel in the
// company, including internal agent-to-agent ones (tagged "observing").
export default function ChatPage() {
  const { id } = useParams<{ id: string }>();
  const search = useSearchParams();
  const fromUrl = search.get("channel");
  const channels = usePoll(() => api.chatChannels(id), 5000, [id]);
  const list = channels.data ?? [];
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(search.get("new") === "1");

  // A channel picked from the sidebar (?channel=) wins; otherwise default to the
  // founder's direct line to the CEO (the standing channel to steer the company),
  // then any thread that needs the founder, else the most recent.
  useEffect(() => {
    if (fromUrl) {
      setSelected(fromUrl);
      return;
    }
    if (selected || list.length === 0) return;
    const ceo = list.find(isCeoDm);
    const needy = list.find((c) => isWaiting(c));
    setSelected((ceo ?? needy ?? list[0]).id);
  }, [fromUrl, list, selected]);

  const active = useMemo(() => list.find((c) => c.id === selected) ?? null, [list, selected]);

  return (
    <div className="chatpage">
      {creating && (
        <NewChannel
          companyId={id}
          onDone={() => { setCreating(false); channels.reload(); }}
          onCancel={() => setCreating(false)}
        />
      )}

      {list.length === 0 && !creating && (
        <div className="empty">No conversations yet. Agents will reach out here when they need you.</div>
      )}

      {active ? (
        <Thread companyId={id} channel={active} onChanged={() => channels.reload()} />
      ) : (
        list.length > 0 && !creating && (
          <div className="empty">Pick a conversation from the sidebar to open it.</div>
        )
      )}
    </div>
  );
}

function isWaiting(c: ChatChannel): boolean {
  return c.waiting_agents.length > 0 || c.pending_decision != null;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
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
  // null = the channel's main timeline; otherwise a thread id (sub-initiative).
  const [activeThread, setActiveThread] = useState<string | null>(null);
  const threads = channel.threads ?? [];
  // Drop the open thread if it disappears (e.g. closed) between polls.
  useEffect(() => {
    if (activeThread && !threads.some((t) => t.id === activeThread)) setActiveThread(null);
  }, [activeThread, threads]);
  const current = threads.find((t) => t.id === activeThread) ?? null;

  const messages = usePoll(
    () => api.chatMessages(companyId, channel.id, activeThread ?? undefined),
    4000,
    [channel.id, activeThread],
  );
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const msgs = messages.data ?? [];
  // Decisions live on the channel's main timeline, not inside a sub-thread.
  const decision = activeThread ? null : channel.pending_decision;

  const isChannel = channel.kind !== "direct";
  const title = channelDisplayName(channel);
  const memberNames = channel.participants.map((p) => p.role ?? p.name);

  // Auto-scroll the timeline to the newest message as it grows.
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [msgs.length, activeThread]);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    try {
      await api.postChatMessage(companyId, channel.id, text, activeThread ?? undefined);
      messages.reload();
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const resolve = async (approve: boolean, note?: string) => {
    if (!decision) return;
    setBusy(true);
    try {
      if (approve) await api.approveDecision(decision.id, note);
      else await api.rejectDecision(decision.id, note);
      messages.reload();
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="convo">
      <header className="ch-head">
        <div className="ch-head-title">
          {isChannel ? <Avatar name={title} square size={26} /> : <Avatar name={title} size={26} />}
          <div className="ch-head-text">
            <strong>
              {isChannel ? `#${title}` : title}
              {current && <span className="muted"> › {current.title}</span>}
            </strong>
            <span className="ch-head-sub muted">
              {channel.purpose && !current ? channel.purpose + " · " : ""}
              {memberNames.length} member{memberNames.length === 1 ? "" : "s"}
              {!founderIsMember(channel) && <span className="tag-observe"> observing</span>}
            </span>
          </div>
        </div>
        <span className="ch-head-members muted" title={memberNames.join(", ")}>
          {memberNames.join(", ")}
        </span>
      </header>

      {threads.length > 0 && (
        <ThreadBar threads={threads} active={activeThread} onPick={(id) => setActiveThread(id)} />
      )}

      <div className="timeline">
        {msgs.length === 0 && !decision && <div className="empty">No messages yet.</div>}
        {msgs.map((m, i) => (
          <MessageRow key={m.id} message={m} prev={msgs[i - 1]} />
        ))}
        {/* A pending decision rides in the timeline as a special message with its
            own Approve/Reject — seamless chat, no separate widget. */}
        {decision && <DecisionMessage decision={decision} onResolve={resolve} busy={busy} />}
        {busy && <div className="muted" style={{ padding: "6px 16px", fontSize: 13 }}>sending…</div>}
        <div ref={endRef} />
      </div>

      <div className="composer">
        <input
          placeholder={
            current
              ? `Message ${current.title}`
              : isChannel
                ? `Message #${title}`
                : `Message ${title}`
          }
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          disabled={busy}
        />
        <button onClick={send} disabled={busy || !input.trim()}>Send</button>
      </div>
    </div>
  );
}

// Tabs to switch between the channel's main timeline and its threads. Each thread
// is a parallel sub-initiative; a "waiting" badge marks one paused for CEO review.
function ThreadBar({
  threads,
  active,
  onPick,
}: {
  threads: ChatThread[];
  active: string | null;
  onPick: (id: string | null) => void;
}) {
  const chip = (selected: boolean): React.CSSProperties => ({
    fontSize: 12,
    padding: "2px 10px",
    borderRadius: 999,
    cursor: "pointer",
    border: "1px solid var(--border, #ccc)",
    background: selected ? "var(--accent, #2563eb)" : "transparent",
    color: selected ? "#fff" : "inherit",
  });
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: "10px 16px 0" }}>
      <button style={{ ...chip(active === null), marginTop: 0 }} onClick={() => onPick(null)}>
        Main
      </button>
      {threads.map((t) => (
        <button
          key={t.id}
          style={{ ...chip(active === t.id), marginTop: 0 }}
          onClick={() => onPick(t.id)}
          title={`${t.message_count} message(s)`}
        >
          {t.title}
          {t.escalation_pending && <span className="status pending"> · waiting</span>}
        </button>
      ))}
    </div>
  );
}

// A pending decision rendered inline as a special chat message: it reads as part
// of the timeline (same avatar gutter + header), but its body is an action panel
// with Approve/Reject and an optional note instead of plain text. Replaces the
// old separate decision widget so the surface stays fully chat-based.
function DecisionMessage({
  decision,
  onResolve,
  busy,
}: {
  decision: Decision;
  onResolve: (approve: boolean, note?: string) => Promise<void>;
  busy: boolean;
}) {
  const [note, setNote] = useState("");
  const who = decision.agent_name ?? "Agent";
  const act = async (approve: boolean) => {
    await onResolve(approve, note.trim() || undefined);
    setNote("");
  };
  return (
    <div className="smsg decision-msg">
      <div className="smsg-gutter">
        <Avatar name={who} size={36} />
      </div>
      <div className="smsg-body">
        <div className="smsg-head">
          <span className="smsg-name">{who}</span>
          {decision.agent_role && <span className="smsg-role">{decision.agent_role}</span>}
          <span className="status waiting_approval">needs your decision</span>
        </div>
        <div className="decision-panel">
          <div className="decision-kind">{decisionKindLabel(decision.kind)}</div>
          <p className="muted decision-hint">
            Review the message above, then approve or reject. A note becomes your guidance to the agent.
          </p>
          <input
            className="decision-note"
            placeholder="Add a note for the agent (optional)…"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            disabled={busy}
          />
          <div className="btnrow">
            <button onClick={() => act(true)} disabled={busy}>Approve</button>
            <button className="ghost" onClick={() => act(false)} disabled={busy}>Reject</button>
          </div>
        </div>
      </div>
    </div>
  );
}

// A single Slack-style message row: avatar + (name · time) + body. Consecutive
// messages from the same sender collapse the avatar/header for a compact thread.
function MessageRow({ message: m, prev }: { message: ChatMessage; prev?: ChatMessage }) {
  const name = m.is_founder
    ? "You"
    : m.sender_name ?? "Agent";
  const grouped =
    prev != null &&
    prev.sender_agent_id === m.sender_agent_id &&
    prev.is_founder === m.is_founder;

  return (
    <div className={`smsg${grouped ? " grouped" : ""}`}>
      <div className="smsg-gutter">
        {!grouped && <Avatar name={name} size={36} />}
      </div>
      <div className="smsg-body">
        {!grouped && (
          <div className="smsg-head">
            <span className="smsg-name">{name}</span>
            {m.sender_role && <span className="smsg-role">{m.sender_role}</span>}
            <span className="smsg-time">{fmtTime(m.created_at)}</span>
          </div>
        )}
        <div className="smsg-text">
          <Markdown>{m.body}</Markdown>
        </div>
      </div>
    </div>
  );
}

function NewChannel({
  companyId,
  onDone,
  onCancel,
}: {
  companyId: string;
  onDone: () => void;
  onCancel: () => void;
}) {
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
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>New channel</h3>
        <button className="ghost" style={{ marginTop: 0 }} onClick={onCancel}>Cancel</button>
      </div>
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
