"use client";

// Galaxia Command — Notification Center.
//
// The founder decision inbox rendered as a list of notifications rather than a
// swipe-to-decide deck. Each item is something that needs the founder — a
// structured decision an agent raised, or an agent parked waiting for a plain
// chat reply — and clicking it opens the relevant conversation, where the founder
// resolves it by replying. Decisions are resolved in Chat now (the reply is
// classified into approve/reject), so the game no longer approves/rejects inline;
// it just points the founder at the right thread.

import Link from "next/link";
import { decisionKindLabel, type Decision } from "@/lib/api";

export function NotificationCenter({
  companyId,
  decisions,
  chatWaiting = 0,
  chatWaitingAgents = [],
  chatHref,
  // When false, render nothing instead of the "all clear" line — the caller is
  // showing another kind of pending item and shouldn't be contradicted.
  showEmpty = true,
}: {
  companyId: string;
  decisions: Decision[];
  chatWaiting?: number;
  // Formatted "Name (role)" labels for the agents parked on a chat reply, so a
  // lone waiter can be named instead of a generic "an agent".
  chatWaitingAgents?: string[];
  chatHref?: string;
  showEmpty?: boolean;
}) {
  const pending = decisions.filter(
    (d) => d.status === "pending" || d.status === "waiting_approval",
  );
  const hasChat = chatWaiting > 0 && !!chatHref;

  if (pending.length === 0 && !hasChat) {
    if (!showEmpty) return null;
    return (
      <p className="muted" style={{ marginTop: 10 }}>
        All clear, Captain. No orders pending.
      </p>
    );
  }

  return (
    <ul className="notif-center">
      {pending.map((d) => (
        <li key={d.id}>
          <Link href={`/c/${companyId}/chat?decision=${d.id}`} className="notif-item">
            <span className="notif-icon" aria-hidden>📩</span>
            <span className="notif-body">
              <span className="notif-title">
                {d.agent_name ?? "An agent"}
                {d.agent_role && <span className="notif-role"> · {d.agent_role}</span>}
                <span className="notif-kind">{decisionKindLabel(d.kind)}</span>
              </span>
              <span className="notif-summary">{preview(d.summary)}</span>
            </span>
            <span className="notif-arrow" aria-hidden>→</span>
          </Link>
        </li>
      ))}
      {hasChat && (
        <li>
          <Link href={chatHref!} className="notif-item">
            <span className="notif-icon" aria-hidden>💬</span>
            <span className="notif-body">
              <span className="notif-title">
                {chatWaiting === 1 && chatWaitingAgents[0]
                  ? `${chatWaitingAgents[0]} is`
                  : chatWaiting === 1
                    ? "An agent is"
                    : `${chatWaiting} agents are`}{" "}
                waiting for your reply
              </span>
              <span className="notif-summary">Open the conversation in Chat to respond.</span>
            </span>
            <span className="notif-arrow" aria-hidden>→</span>
          </Link>
        </li>
      )}
    </ul>
  );
}

// Decision summaries can be markdown / multi-line (e.g. a full plan-approval);
// show a compact one-line preview so every notification stays the same height.
function preview(summary: string): string {
  const line =
    (summary || "")
      .split("\n")
      .map((l) => l.replace(/[#*`>_]/g, "").trim())
      .find(Boolean) ?? "";
  return line.length > 120 ? line.slice(0, 117) + "…" : line;
}
