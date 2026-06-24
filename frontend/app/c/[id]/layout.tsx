"use client";

import Link from "next/link";
import { usePathname, useParams, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { api } from "@/lib/api";

const TABS = [
  ["", "Overview"],
  ["org", "Org"],
  ["budget", "Budget"],
  ["tasks", "Tasks"],
  ["reports", "Reports"],
  ["governance", "Governance"],
  ["communications", "Comms"],
  ["decisions", "Decisions"],
  ["memory", "Memory"],
  ["files", "Files"],
  ["marketplace", "Marketplace"],
  ["copilot", "Copilot"],
  ["settings", "Settings"],
] as const;

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const params = useParams<{ id: string }>();
  const pathname = usePathname();
  const router = useRouter();
  const base = `/c/${params.id}`;

  return (
    <div>
      <div className="topbar">
        <span className="brand">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/abos-logo.png" alt="" className="brand-logo" width={26} height={26} />
          ABOS
        </span>
        <button
          className="ghost"
          style={{ marginTop: 0 }}
          onClick={() => { api.logout(); router.push("/"); }}
        >
          Log out
        </button>
      </div>
      <nav className="nav">
        {TABS.map(([slug, label]) => {
          const href = slug ? `${base}/${slug}` : base;
          const active = pathname === href;
          return (
            <Link key={slug} href={href} className={active ? "active" : ""}>
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="dash">{children}</div>
    </div>
  );
}
