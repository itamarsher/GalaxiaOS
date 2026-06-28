"use client";

import Link from "next/link";
import { usePathname, useParams, useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { api, type ChatChannel } from "@/lib/api";
import { usePoll } from "@/lib/useApi";
import { Avatar, channelDisplayName, founderIsMember } from "@/lib/chat";

// A Slack-style workspace. The left rail carries the workspace's "Spaces" (the
// dashboard surfaces — Org, Budget, Tasks, …) plus the live collaboration:
// Channels the fleet coordinates in and Direct messages. The founder sees every
// channel in the company, not just their own DMs — agent-to-agent conversations
// show too (tagged "observing" when the founder isn't a participant). Onboarding
// and Settings stay out of the rail — onboarding is its own flow, Settings sits
// in the footer.
const SPACES = [
  ["", "Home"],
  ["org", "Org"],
  ["budget", "Budget"],
  ["tasks", "Tasks"],
  ["reports", "Reports"],
  ["governance", "Governance"],
  ["communications", "Comms"],
  ["memory", "Memory"],
  ["files", "Files"],
  ["marketplace", "Marketplace"],
  ["copilot", "Copilot"],
] as const;

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const params = useParams<{ id: string }>();
  const pathname = usePathname();
  const search = useSearchParams();
  const router = useRouter();
  const base = `/c/${params.id}`;
  const channels = usePoll(() => api.chatChannels(params.id), 8000, [params.id]);
  const convos = channels.data ?? [];
  const activeChannel = search.get("channel");
  const onChat = pathname === `${base}/chat`;

  // Slack splits the rail into Channels and Direct messages; we do the same.
  const channelList = convos.filter((c) => c.kind !== "direct");
  const dmList = convos.filter((c) => c.kind === "direct");

  const chatLink = (c: ChatChannel) => {
    const active = onChat && activeChannel === c.id;
    const isChannel = c.kind !== "direct";
    const label = channelDisplayName(c);
    return (
      <Link
        key={c.id}
        href={`${base}/chat?channel=${c.id}`}
        className={`chat-item${active ? " active" : ""}`}
        title={isChannel ? `#${label}` : label}
      >
        {isChannel ? (
          <Avatar name={label} square size={18} />
        ) : (
          <Avatar name={label} size={18} />
        )}
        <span className="chat-item-name">{label}</span>
        {!founderIsMember(c) && <span className="tag-observe">observing</span>}
        {isWaiting(c) && <span className="dot" />}
      </Link>
    );
  };

  return (
    <div className="shell">
      <aside className="sidebar">
        <span className="brand">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/galaxiaos-logo.png" alt="" className="brand-logo" width={26} height={26} />
          GalaxiaOS
        </span>

        <div>
          <div className="grp-label">Spaces</div>
          {SPACES.map(([slug, label]) => {
            const href = slug ? `${base}/${slug}` : base;
            const active = pathname === href;
            return (
              <Link key={slug} href={href} className={active ? "active" : ""}>
                {label}
              </Link>
            );
          })}
        </div>

        <div>
          <div className="grp-label grp-label-row">
            <span>Channels</span>
            <Link href={`${base}/chat?new=1`} className="grp-add" title="New channel">
              +
            </Link>
          </div>
          <Link href={`${base}/chat`} className={`chat-item${onChat && !activeChannel ? " active" : ""}`}>
            <span className="chat-item-name">All conversations</span>
            {convos.some(isWaiting) && <span className="dot" />}
          </Link>
          {channelList.map(chatLink)}
          {channelList.length === 0 && <div className="grp-empty">No channels yet</div>}
        </div>

        <div>
          <div className="grp-label">Direct messages</div>
          {dmList.map(chatLink)}
          {dmList.length === 0 && <div className="grp-empty">No direct messages yet</div>}
        </div>

        <div className="spacer" />
        <div>
          <Link href={`${base}/settings`} className={pathname === `${base}/settings` ? "active" : ""}>
            Settings
          </Link>
          <button
            className="navbtn"
            style={{ background: "none", border: 0, cursor: "pointer", width: "100%" }}
            onClick={() => { api.logout(); router.push("/"); }}
          >
            Log out
          </button>
        </div>
      </aside>

      <main className="shell-main">
        <div className="dash">{children}</div>
      </main>
    </div>
  );
}

function isWaiting(c: { waiting_agents: string[]; pending_decision: unknown | null }): boolean {
  return c.waiting_agents.length > 0 || c.pending_decision != null;
}
