// Shared helpers for the Slack-style chat surface: display names, founder
// membership, and the little colored initials avatar used in the sidebar and
// the message pane. A participant/sender with a null agent id is the founder.

import type { ChatChannel } from "@/lib/api";

/** Is the founder an actual participant, or are they observing internal agent chatter? */
export function founderIsMember(c: ChatChannel): boolean {
  return c.participants.some((p) => p.agent_id == null);
}

/** The founder's direct line to the CEO — the standing channel to steer the
 *  company, opened by default. A DM whose agent participant is the CEO. */
export function isCeoDm(c: ChatChannel): boolean {
  return c.kind === "direct" && c.participants.some((p) => p.role === "ceo");
}

/** Slack-style display name: the bare channel name for channels; for a DM, the
 *  other members' names (so a founder↔agent thread reads as the agent, not as a
 *  raw "ceo agent ↔ founder" title). */
export function channelDisplayName(c: ChatChannel): string {
  if (c.kind === "direct") {
    const others = c.participants.filter((p) => p.agent_id != null).map((p) => p.name);
    if (others.length) return others.join(", ");
    return c.name.replace(/\s*↔\s*founder\s*$/i, "").trim() || c.name;
  }
  return c.name;
}

/** One- or two-letter initials for an avatar, ignoring chat decoration (#, ↔). */
export function initials(name: string): string {
  const parts = name.replace(/[#↔]/g, " ").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// A small, fixed palette; pick deterministically from the name so an agent keeps
// the same avatar colour everywhere it appears.
const AVATAR_COLORS = [
  "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981",
  "#06b6d4", "#3b82f6", "#ef4444", "#14b8a6", "#a855f7",
];

export function colorFor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

/** Colored initials disc. ``square`` is used for channels (rounded square + #). */
export function Avatar({
  name,
  size = 20,
  square = false,
}: {
  name: string;
  size?: number;
  square?: boolean;
}) {
  return (
    <span
      className="avatar"
      style={{
        background: colorFor(name),
        width: size,
        height: size,
        fontSize: Math.round(size * 0.42),
        borderRadius: square ? Math.round(size * 0.28) : "50%",
      }}
      aria-hidden
    >
      {square ? "#" : initials(name)}
    </span>
  );
}
