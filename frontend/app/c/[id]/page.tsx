"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { api, fmtUsd, sortTasksForView, statusLabel } from "@/lib/api";
import { usePoll, useLiveTasks } from "@/lib/useApi";
import { Markdown } from "@/lib/markdown";

export default function Overview() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const company = usePoll(() => api.company(id), 0, [id]);
  const budget = usePoll(() => api.budget(id), 5000, [id]);
  const chatChannels = usePoll(() => api.chatChannels(id), 5000, [id]);
  const digest = usePoll(() => api.digestLatest(id), 0, [id]);
  const sites = usePoll(() => api.sites(id), 10000, [id]);

  // Live task stream (SSE when healthy, polling fallback) so the founder sees work
  // happening and the feed keeps refreshing even when SSE drops (see useLiveTasks).
  const tasks = useLiveTasks(id);
  const [justLaunched, setJustLaunched] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setJustLaunched(new URLSearchParams(window.location.search).get("launched") === "1");
    }
  }, []);

  const b = budget.data?.budget;
  const pct = b && b.limit_cents ? Math.min(100, (b.spent_cents / b.limit_cents) * 100) : 0;
  const counts = tasks.reduce<Record<string, number>>((acc, t) => {
    acc[t.status] = (acc[t.status] ?? 0) + 1;
    return acc;
  }, {});
  const inFlight = (counts["running"] ?? 0) + (counts["queued"] ?? 0);
  // Decisions awaiting the founder float to the top, done tasks sink to the bottom.
  const recent = sortTasksForView(tasks).slice(0, 6);

  const deleteCompany = async () => {
    if (!window.confirm(
      "Delete this company and ALL its data (agents, tasks, budget, history)? " +
      "This stops it running and cannot be undone."
    )) return;
    setDeleting(true);
    try {
      await api.deleteCompany(id);
      router.push("/");
    } catch (e) {
      alert(String(e instanceof Error ? e.message : e));
      setDeleting(false);
    }
  };

  // Reset this company to a fresh draft: wipes its generated org and all
  // operational state (tasks, runs, budget spend, memory, chat, sites…) and
  // rebuilds the default fleet, keeping the mission and saved API keys. Lands at
  // plan-approval, so we return to onboarding to review and relaunch.
  const [resetting, setResetting] = useState(false);
  const resetCompany = async () => {
    if (!window.confirm(
      "Reset this company? This wipes its agents, tasks, budget history, memory and " +
      "activity and rebuilds a fresh draft to relaunch. Its mission and saved API keys " +
      "are preserved. This cannot be undone."
    )) return;
    setResetting(true);
    try {
      await api.resetCompany(id);
      alert("Company reset — rebuilt as a fresh draft. Review the plan and relaunch when ready.");
      router.push("/");
    } catch (e) {
      alert(String(e instanceof Error ? e.message : e));
      setResetting(false);
    }
  };

  return (
    <div>
      <h2>{company.data?.name ?? "Company"}</h2>
      <p className="muted">
        Status: <span className={`status ${company.data?.status}`}>{company.data?.status ?? "—"}</span>
      </p>

      <div className="card">
        <div className="step" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {inFlight > 0 && <span className="spinner" style={{ width: 14, height: 14 }} />}
          <span>
            {justLaunched && inFlight > 0
              ? "🚀 Launched — initial work in progress"
              : inFlight > 0
                ? "Live activity"
                : "Tasks"}
          </span>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <span className="pill">{counts["running"] ?? 0} running</span>
          <span className="pill">{counts["queued"] ?? 0} queued</span>
          <span className="pill">{counts["done"] ?? 0} done</span>
          {(counts["waiting_approval"] ?? 0) > 0 && (
            <span className="pill">{counts["waiting_approval"]} awaiting you</span>
          )}
        </div>
        {recent.length > 0 ? (
          <div style={{ marginTop: 12 }}>
            {recent.map((t) => (
              <Link key={t.id} href={`/c/${id}/tasks?task=${t.id}`} className="actrow">
                <span className="goal">{"— ".repeat(t.depth)}{t.goal}</span>
                <span className={`status ${t.status}`}>{statusLabel(t.status)}</span>
              </Link>
            ))}
          </div>
        ) : (
          <p className="muted" style={{ marginTop: 10 }}>
            {inFlight > 0 ? "Agents are kicking off the first initiatives…" : "No tasks yet."}
          </p>
        )}
        <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>
          This updates live — tap a task for details. Open the Tasks tab for the full tree.
        </p>
      </div>

      <div className="grid2">
        <div className="card">
          <div className="step">Budget</div>
          {b ? (
            <>
              <div className="kv"><span>Spent</span><span>{fmtUsd(b.spent_cents)} / {fmtUsd(b.limit_cents)}</span></div>
              <div className="bar" style={{ marginTop: 8 }}><span style={{ width: `${pct}%` }} /></div>
              <div className="kv" style={{ marginTop: 8 }}><span>Reserved</span><span>{fmtUsd(b.reserved_cents)}</span></div>
            </>
          ) : <p className="muted">loading…</p>}
        </div>

        <div className="card">
          <div className="step">Needs you</div>
          <p style={{ fontSize: 32, margin: "8px 0" }}>
            {(chatChannels.data ?? []).filter(
              (c) => c.waiting_agents.length > 0 || c.pending_decision != null,
            ).length}
          </p>
          <p className="muted">Chat threads where an agent is waiting for your reply. See the Chat tab.</p>
        </div>
      </div>

      <div className="card">
        <div className="step" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>Latest digest{digest.data?.period_date ? ` · ${digest.data.period_date}` : ""}</span>
          <button className="ghost" style={{ marginTop: 0, padding: "6px 12px", fontSize: 12 }}
            onClick={() => api.generateDigest(id).then(() => digest.reload())}>
            Refresh
          </button>
        </div>
        {digest.data?.summary_md ? (
          <Markdown className="digest-md">{digest.data.summary_md}</Markdown>
        ) : (
          <div className="empty">Preparing your first digest…</div>
        )}
      </div>

      {sites.data && sites.data.length > 0 && (
        <div className="card">
          <div className="step">Sites &amp; domains</div>
          <div style={{ marginTop: 10 }}>
            {sites.data.map((s) => (
              <div key={s.id} className="kv" style={{ flexWrap: "wrap" }}>
                <span>
                  {s.deployment_url ? (
                    <a className="md" href={s.deployment_url} target="_blank" rel="noopener noreferrer"
                       style={{ color: "var(--accent-strong)" }}>{s.title}</a>
                  ) : s.title}
                </span>
                <span className="muted" style={{ fontSize: 12 }}>
                  {s.domains.length > 0
                    ? s.domains.map((d) => `${d.domain} (${d.status})`).join(", ")
                    : "no domain connected"}
                </span>
              </div>
            ))}
          </div>
          <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>
            Landing pages your agents published, and the status of any domain being connected.
          </p>
        </div>
      )}

      <div className="card danger-zone">
        <div className="step">Danger zone</div>
        <p className="muted">
          Reset wipes this company&apos;s agents, tasks, budget history, memory and activity and
          rebuilds a fresh draft to relaunch — keeping its mission and saved API keys. Delete
          removes the company and everything under it. Neither can be undone.
        </p>
        <div className="btnrow">
          <button className="ghost danger" disabled={resetting || deleting} onClick={resetCompany}>
            {resetting ? "Resetting…" : "Reset company"}
          </button>
          <button className="ghost danger" disabled={deleting || resetting} onClick={deleteCompany}>
            {deleting ? "Deleting…" : "Delete company"}
          </button>
        </div>
      </div>
    </div>
  );
}
