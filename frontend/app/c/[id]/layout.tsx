"use client";

import Link from "next/link";
import { usePathname, useParams, useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/useApi";

// Every workspace is a "channel". The former top-nav pages are default channels
// (Spaces); live agent/founder threads are Conversations. Onboarding and Settings
// are intentionally NOT folded in — onboarding is its own flow and Settings sits
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

  return (
    <div className="shell">
      <aside className="sidebar">
        <span className="brand">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/abos-logo.png" alt="" className="brand-logo" width={26} height={26} />
          ABOS
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
          <div className="grp-label">Chat</div>
          <Link href={`${base}/chat`} className={onChat && !activeChannel ? "active" : ""}>
            <span>All conversations</span>
            {convos.some(isWaiting) && <span className="dot" />}
          </Link>
          {convos.map((c) => {
            const active = onChat && activeChannel === c.id;
            const title = c.kind === "direct" ? c.name : `# ${c.name}`;
            return (
              <Link
                key={c.id}
                href={`${base}/chat?channel=${c.id}`}
                className={active ? "active" : ""}
                title={title}
              >
                <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{title}</span>
                {isWaiting(c) && <span className="dot" />}
              </Link>
            );
          })}
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
