"use client";

// Galaxia Command — the Systems Console.
//
// The visual dashboard (canvas station + core HUD) carries the live, at-a-glance
// state. Everything else the founder might otherwise leave the game to see — the
// ledger, governance, comms, reports, memory, crew, growth, files, marketplace,
// capability backlog, the copilot, and the raw system event counters — folds in
// here as a dock of panels so it's all part of one screen. A panel only mounts
// (and therefore polls) while its tab is open, so idle tabs cost nothing.

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  api,
  fmtUsd,
  statusLabel,
  type AgentSpend,
  type BudgetView,
} from "@/lib/api";
import { usePoll } from "@/lib/useApi";
import { Markdown } from "@/lib/markdown";

type TabKey =
  | "stats" | "ledger" | "governance" | "comms" | "reports" | "memory"
  | "crew" | "growth" | "files" | "market" | "requests" | "copilot";

const TABS: { key: TabKey; icon: string; label: string }[] = [
  { key: "stats", icon: "📊", label: "Stats" },
  { key: "ledger", icon: "💰", label: "Ledger" },
  { key: "governance", icon: "🛡️", label: "Governance" },
  { key: "comms", icon: "📡", label: "Comms" },
  { key: "reports", icon: "📄", label: "Reports" },
  { key: "memory", icon: "🧠", label: "Memory" },
  { key: "crew", icon: "🧑‍🚀", label: "Crew" },
  { key: "growth", icon: "🌐", label: "Growth" },
  { key: "files", icon: "📁", label: "Files" },
  { key: "market", icon: "🛰️", label: "Market" },
  { key: "requests", icon: "🧩", label: "Backlog" },
  { key: "copilot", icon: "✨", label: "Copilot" },
];

export function ConsoleDock({
  companyId,
  budget,
}: {
  companyId: string;
  budget: BudgetView | null;
}) {
  const [tab, setTab] = useState<TabKey | null>(null);

  return (
    <div className={`console-dock${tab ? " open" : ""}`}>
      {tab && (
        <div className="console-body" role="region" aria-label={`${tab} panel`}>
          <button className="console-close" onClick={() => setTab(null)} aria-label="Close panel">
            ✕
          </button>
          <Panel tab={tab} companyId={companyId} budget={budget} />
        </div>
      )}
      <div className="console-tabs" role="tablist" aria-label="Systems console">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={`console-tab${tab === t.key ? " active" : ""}`}
            onClick={() => setTab(tab === t.key ? null : t.key)}
          >
            <span className="console-tab-icon" aria-hidden>{t.icon}</span>
            <span className="console-tab-label">{t.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function Panel(props: { tab: TabKey; companyId: string; budget: BudgetView | null }) {
  switch (props.tab) {
    case "stats": return <StatsPanel companyId={props.companyId} />;
    case "ledger": return <LedgerPanel companyId={props.companyId} budget={props.budget} />;
    case "governance": return <GovernancePanel companyId={props.companyId} />;
    case "comms": return <CommsPanel companyId={props.companyId} />;
    case "reports": return <ReportsPanel companyId={props.companyId} />;
    case "memory": return <MemoryPanel companyId={props.companyId} />;
    case "crew": return <CrewPanel companyId={props.companyId} />;
    case "growth": return <GrowthPanel companyId={props.companyId} />;
    case "files": return <FilesPanel companyId={props.companyId} />;
    case "market": return <MarketPanel companyId={props.companyId} />;
    case "requests": return <RequestsPanel companyId={props.companyId} />;
    case "copilot": return <CopilotPanel companyId={props.companyId} />;
  }
}

// ── Shared bits ───────────────────────────────────────────────────────────────
function PanelHead({ title, href, hint }: { title: string; href?: string; hint?: string }) {
  return (
    <div className="panel-head">
      <h3>{title}</h3>
      {hint && <span className="muted panel-hint">{hint}</span>}
      {href && <Link href={href} className="panel-fulllink">Open full view →</Link>}
    </div>
  );
}
function Empty({ children }: { children: React.ReactNode }) {
  return <p className="muted panel-empty">{children}</p>;
}
function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

// ── Stats: the raw per-company event counters (the new events table) ──────────
const EVENT_META: Record<string, { label: string; icon: string }> = {
  llm_call: { label: "LLM calls", icon: "🧠" },
  tool_call: { label: "Tool calls", icon: "🔧" },
  task_started: { label: "Tasks started", icon: "▶" },
  task_completed: { label: "Tasks done", icon: "✓" },
  task_failed: { label: "Tasks failed", icon: "✕" },
  run_started: { label: "Cycles run", icon: "🚀" },
  decision_requested: { label: "Approvals asked", icon: "🗳" },
  external_message: { label: "Messages sent", icon: "📨" },
  error_escalated: { label: "Errors escalated", icon: "🚨" },
};
function StatsPanel({ companyId }: { companyId: string }) {
  const counters = usePoll(() => api.eventCounters(companyId), 8000, [companyId]);
  const rows = counters.data?.counters ?? [];
  const known = TABS_ORDER_STATS(rows);
  return (
    <div className="panel">
      <PanelHead title="System event counters" hint="Everything the fleet has done, tallied live" />
      {rows.length === 0 ? (
        <Empty>No events counted yet — advance a cycle to put the fleet to work.</Empty>
      ) : (
        <div className="stat-grid">
          {known.map((c) => {
            const meta = EVENT_META[c.event_type] ?? { label: c.event_type, icon: "•" };
            return (
              <div className="stat-cell" key={c.event_type}>
                <span className="stat-icon" aria-hidden>{meta.icon}</span>
                <span className="stat-num">{c.count.toLocaleString()}</span>
                <span className="stat-label">{meta.label}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
function TABS_ORDER_STATS(rows: { event_type: string; count: number }[]) {
  // Show known events in a stable, meaningful order; unknown ones after.
  const order = Object.keys(EVENT_META);
  return [...rows].sort(
    (a, b) => (order.indexOf(a.event_type) + 1 || 99) - (order.indexOf(b.event_type) + 1 || 99),
  );
}

// ── Ledger: budget by category + by agent ─────────────────────────────────────
function LedgerPanel({ companyId, budget }: { companyId: string; budget: BudgetView | null }) {
  const byAgent = usePoll(() => api.budgetByAgent(companyId), 10000, [companyId]);
  const agents = byAgent.data ?? [];
  const [open, setOpen] = useState<string | null>(null);
  const byCategory = useMemo(
    () => Object.entries(budget?.by_category ?? {}).sort((a, b) => b[1] - a[1]),
    [budget],
  );
  return (
    <div className="panel">
      <PanelHead title="Ledger" href={`/c/${companyId}/budget`} />
      {budget && (
        <div className="ledger-summary">
          <Meter label="Spent" value={budget.budget.spent_cents} of={budget.budget.limit_cents} />
          <span className="muted" style={{ fontSize: 12 }}>
            {fmtUsd(budget.budget.reserved_cents)} reserved
          </span>
        </div>
      )}
      {byCategory.length > 0 && (
        <div className="chip-row">
          {byCategory.map(([cat, cents]) => (
            <span key={cat} className="pill">{cat}: {fmtUsd(cents)}</span>
          ))}
        </div>
      )}
      <div className="panel-scroll">
        {agents.length === 0 && <Empty>No spend recorded yet.</Empty>}
        {agents.map((a) => (
          <AgentSpendRow
            key={a.agent_id ?? "unassigned"}
            spend={a}
            open={open === (a.agent_id ?? "u")}
            onToggle={() => setOpen(open === (a.agent_id ?? "u") ? null : a.agent_id ?? "u")}
          />
        ))}
      </div>
    </div>
  );
}
function AgentSpendRow({ spend, open, onToggle }: { spend: AgentSpend; open: boolean; onToggle: () => void }) {
  return (
    <div className="ledger-row">
      <button className="ledger-agent" onClick={onToggle} aria-expanded={open}>
        <span>{spend.agent_name ?? "Unassigned"}</span>
        <span className="muted">{spend.agent_role ?? ""}</span>
        <span className="ledger-amt">{fmtUsd(spend.total_cents)}</span>
      </button>
      {open && (
        <div className="ledger-entries">
          {spend.entries.length === 0 && <Empty>No line items.</Empty>}
          {spend.entries.slice(0, 40).map((e) => (
            <div className="ledger-entry" key={e.id}>
              <span className="pill sm">{e.category}</span>
              <span className="ledger-desc">{e.description ?? e.vendor ?? e.sku ?? "—"}</span>
              <span className="ledger-amt">{fmtUsd(e.amount_cents)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Governance: policies, breakers, reputation ────────────────────────────────
function GovernancePanel({ companyId }: { companyId: string }) {
  const policies = usePoll(() => api.policies(companyId), 15000, [companyId]);
  const breakers = usePoll(() => api.breakers(companyId), 10000, [companyId]);
  const reputation = usePoll(() => api.reputation(companyId), 15000, [companyId]);
  const [busy, setBusy] = useState<string | null>(null);
  const reset = async (bid: string) => {
    setBusy(bid);
    try { await api.resetBreaker(companyId, bid); await breakers.reload(); }
    finally { setBusy(null); }
  };
  const trippedFirst = [...(breakers.data ?? [])].sort((a, b) => Number(b.state === "tripped") - Number(a.state === "tripped"));
  return (
    <div className="panel">
      <PanelHead title="Governance" href={`/c/${companyId}/governance`} />
      <div className="panel-scroll">
        <h4 className="panel-sub">Circuit breakers</h4>
        {trippedFirst.length === 0 && <Empty>No breakers.</Empty>}
        {trippedFirst.map((b) => (
          <div className="gov-row" key={b.id}>
            <span className={`status ${b.state === "tripped" ? "bad" : "ok"}`}>{b.type}</span>
            <span className="muted gov-reason">{b.tripped_reason ?? b.state}</span>
            {b.state === "tripped" && (
              <button className="ghost sm" disabled={busy === b.id} onClick={() => reset(b.id)}>
                {busy === b.id ? "…" : "Reset"}
              </button>
            )}
          </div>
        ))}
        <h4 className="panel-sub">Crew reputation</h4>
        {(reputation.data ?? []).length === 0 && <Empty>No reputation yet.</Empty>}
        {(reputation.data ?? []).map((r) => (
          <div className="gov-row" key={r.agent_id}>
            <span className="gov-name">{r.agent_name ?? r.agent_role ?? "agent"}</span>
            <span className="muted" style={{ fontSize: 12 }}>
              trust {pct(r.trust)} · acc {pct(r.accuracy)} · roi {pct(r.roi)} · rel {pct(r.reliability)} · n{r.sample_count}
            </span>
          </div>
        ))}
        <h4 className="panel-sub">Policies</h4>
        {(policies.data ?? []).length === 0 && <Empty>No policies.</Empty>}
        {(policies.data ?? []).map((p) => (
          <div className="gov-row" key={p.id}>
            <span className={`status ${p.enabled ? "ok" : ""}`}>{p.effect}</span>
            <span className="gov-name">{p.name}</span>
            <span className="muted" style={{ fontSize: 12 }}>{p.scope}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Comms: outbound external-message log + approval toggle ─────────────────────
function CommsPanel({ companyId }: { companyId: string }) {
  const msgs = usePoll(() => api.externalMessages(companyId), 10000, [companyId]);
  const approval = usePoll(() => api.externalApproval(companyId), 20000, [companyId]);
  const [busy, setBusy] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const toggle = async () => {
    setBusy(true);
    try { await api.setExternalApproval(companyId, !(approval.data?.enabled)); await approval.reload(); }
    finally { setBusy(false); }
  };
  return (
    <div className="panel">
      <PanelHead title="Communications" href={`/c/${companyId}/communications`} />
      <label className="comms-toggle">
        <input type="checkbox" checked={approval.data?.enabled ?? false} disabled={busy} onChange={toggle} />
        Require my approval on every outbound message
      </label>
      <div className="panel-scroll">
        {(msgs.data ?? []).length === 0 && <Empty>No outbound messages yet.</Empty>}
        {(msgs.data ?? []).map((m) => (
          <div className="comms-row" key={m.id}>
            <button className="comms-line" onClick={() => setOpenId(openId === m.id ? null : m.id)}>
              <span className="pill sm">{m.channel}</span>
              <span className="comms-subject">{m.subject ?? m.recipient ?? m.tool}</span>
              <span className={`status ${statusClass(m.status)}`}>{statusLabel(m.status)}</span>
            </button>
            {openId === m.id && (
              <div className="comms-body">
                <div className="muted" style={{ fontSize: 12 }}>
                  {m.agent_name ?? "agent"} · to {m.recipient ?? "—"}
                </div>
                {m.body && <p style={{ whiteSpace: "pre-wrap", margin: "6px 0 0" }}>{m.body}</p>}
                {m.detail && <p className="muted" style={{ fontSize: 12 }}>{m.detail}</p>}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
function statusClass(s: string): string {
  if (s === "sent") return "ok";
  if (s === "failed" || s === "blocked" || s === "rejected") return "bad";
  return "";
}

// ── Reports: latest digest + generated reports ────────────────────────────────
function ReportsPanel({ companyId }: { companyId: string }) {
  const digest = usePoll(() => api.digestLatest(companyId), 30000, [companyId]);
  const [busy, setBusy] = useState(false);
  const refresh = async () => { setBusy(true); try { await api.generateDigest(companyId); await digest.reload(); } finally { setBusy(false); } };
  return (
    <div className="panel">
      <PanelHead title="Daily digest" href={`/c/${companyId}/reports`} />
      <button className="ghost sm" onClick={refresh} disabled={busy} style={{ alignSelf: "flex-start" }}>
        {busy ? "Generating…" : "Regenerate"}
      </button>
      <div className="panel-scroll">
        {digest.data?.summary_md
          ? <Markdown className="md">{digest.data.summary_md}</Markdown>
          : <Empty>No digest yet — generate one to summarize the day.</Empty>}
      </div>
    </div>
  );
}

// ── Memory: the company's long-term memory entries ────────────────────────────
function MemoryPanel({ companyId }: { companyId: string }) {
  const [q, setQ] = useState("");
  const memory = usePoll(() => api.memory(companyId, q || undefined), 0, [companyId]);
  return (
    <div className="panel">
      <PanelHead title="Company memory" href={`/c/${companyId}/memory`} />
      <form
        onSubmit={(e) => { e.preventDefault(); memory.reload(); }}
        className="panel-searchrow"
      >
        <input className="panel-input" placeholder="Search memory…" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="ghost sm" type="submit">Search</button>
      </form>
      <div className="panel-scroll">
        {(memory.data ?? []).length === 0 && <Empty>No memories match.</Empty>}
        {(memory.data ?? []).map((m) => (
          <div className="mem-row" key={m.id}>
            <div className="mem-head"><span className="pill sm">{m.type}</span><b>{m.title}</b></div>
            <p className="muted mem-content">{m.content}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Crew: org playbook + per-agent prompts/autonomy ───────────────────────────
function CrewPanel({ companyId }: { companyId: string }) {
  const org = usePoll(() => api.org(companyId), 15000, [companyId]);
  const playbook = usePoll(() => api.playbook(companyId), 30000, [companyId]);
  const agents = org.data?.agents ?? [];
  return (
    <div className="panel">
      <PanelHead title="Crew & playbook" href={`/c/${companyId}/org`} />
      <div className="panel-scroll">
        <h4 className="panel-sub">Company playbook</h4>
        {playbook.data?.playbook
          ? <pre className="playbook-view">{playbook.data.playbook}</pre>
          : <Empty>No custom playbook.</Empty>}
        <h4 className="panel-sub">Fleet ({agents.length})</h4>
        {agents.map((a) => (
          <div className="gov-row" key={a.id}>
            <span className="gov-name">{a.name}</span>
            <span className="muted" style={{ fontSize: 12 }}>{a.role} · {statusLabel(a.status)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Growth: sites, leads, owned domains ───────────────────────────────────────
function GrowthPanel({ companyId }: { companyId: string }) {
  const sites = usePoll(() => api.sites(companyId), 15000, [companyId]);
  const domains = usePoll(() => api.domains(companyId), 20000, [companyId]);
  return (
    <div className="panel">
      <PanelHead title="Growth" href={`/c/${companyId}/domains`} />
      <div className="panel-scroll">
        <h4 className="panel-sub">Sites & leads</h4>
        {(sites.data ?? []).length === 0 && <Empty>No sites published yet.</Empty>}
        {(sites.data ?? []).map((s) => (
          <div className="gov-row" key={s.id}>
            <span className="gov-name">{s.title}</span>
            <span className="muted" style={{ fontSize: 12 }}>
              {statusLabel(s.status)} · {s.lead_count} leads
              {s.domains.map((d) => ` · ${d.domain} (${statusLabel(d.status)})`).join("")}
            </span>
          </div>
        ))}
        <h4 className="panel-sub">Owned domains</h4>
        {(domains.data ?? []).length === 0 && <Empty>No domains owned.</Empty>}
        {(domains.data ?? []).map((d) => (
          <div className="gov-row" key={d.id}>
            <span className="gov-name">{d.domain}</span>
            <span className="muted" style={{ fontSize: 12 }}>{statusLabel(d.status)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Files: the company file store ─────────────────────────────────────────────
function FilesPanel({ companyId }: { companyId: string }) {
  const files = usePoll(() => api.companyFiles(companyId), 20000, [companyId]);
  return (
    <div className="panel">
      <PanelHead title="Files" href={`/c/${companyId}/files`} />
      <div className="panel-scroll">
        {(files.data ?? []).length === 0 && <Empty>No files yet.</Empty>}
        {(files.data ?? []).map((f) => (
          <div className="gov-row" key={f.id}>
            <span className="pill sm">{f.category}</span>
            <span className="gov-name">{f.name}</span>
            {f.web_url ? <a href={f.web_url} target="_blank" rel="noreferrer" className="panel-fulllink">open</a> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Marketplace: hireable agents ──────────────────────────────────────────────
function MarketPanel({ companyId }: { companyId: string }) {
  const listings = usePoll(() => api.marketplace(), 30000, [companyId]);
  const [busy, setBusy] = useState<string | null>(null);
  const hire = async (lid: string) => { setBusy(lid); try { await api.hireAgent(companyId, lid); await listings.reload(); } finally { setBusy(null); } };
  return (
    <div className="panel">
      <PanelHead title="Marketplace" href={`/c/${companyId}/marketplace`} />
      <div className="panel-scroll">
        {(listings.data ?? []).length === 0 && <Empty>No agents listed.</Empty>}
        {(listings.data ?? []).map((l) => (
          <div className="market-row" key={l.id}>
            <div>
              <b>{l.name}</b> <span className="muted">· {l.role}</span>
              <div className="muted market-desc">{l.description}</div>
              <div className="muted" style={{ fontSize: 12 }}>
                {l.provider} · {fmtUsd(l.price_cents)} · trust {pct(l.trust)} · roi {pct(l.roi)}
              </div>
            </div>
            <button className="ghost sm" disabled={busy === l.id} onClick={() => hire(l.id)}>
              {busy === l.id ? "…" : "Hire"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Backlog: capability / bug feature requests ────────────────────────────────
function RequestsPanel({ companyId }: { companyId: string }) {
  const reqs = usePoll(() => api.featureRequests(companyId), 20000, [companyId]);
  return (
    <div className="panel">
      <PanelHead title="Capability backlog" href={`/c/${companyId}/capabilities`} />
      <div className="panel-scroll">
        {(reqs.data ?? []).length === 0 && <Empty>No requests filed.</Empty>}
        {(reqs.data ?? []).map((r) => (
          <div className="req-row" key={r.id}>
            <div className="req-head">
              <span className={`pill sm ${r.kind === "bug" ? "danger" : ""}`}>{r.kind}</span>
              <b>{r.title}</b>
              <span className="muted" style={{ fontSize: 12 }}>▲ {r.vote_count}</span>
            </div>
            <div className="muted" style={{ fontSize: 12 }}>
              {statusLabel(r.status)}
              {r.github_issue_url && (
                <> · <a href={r.github_issue_url} target="_blank" rel="noreferrer" className="panel-fulllink">#{r.github_issue_number}</a></>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Copilot: ask a question about the company ─────────────────────────────────
function CopilotPanel({ companyId }: { companyId: string }) {
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    try { const r = await api.copilotAsk(companyId, q.trim()); setAnswer(r.answer); }
    catch { setAnswer("Sorry — the copilot could not answer that."); }
    finally { setBusy(false); }
  };
  return (
    <div className="panel">
      <PanelHead title="Founder copilot" href={`/c/${companyId}/copilot`} />
      <form onSubmit={ask} className="panel-searchrow">
        <input className="panel-input" placeholder="Ask about your company…" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="ghost sm" type="submit" disabled={busy}>{busy ? "…" : "Ask"}</button>
      </form>
      <div className="panel-scroll">
        {answer ? <Markdown className="md">{answer}</Markdown> : <Empty>Ask a grounded question — the copilot answers from your live company state.</Empty>}
      </div>
    </div>
  );
}

// ── A tiny inline meter (spent-of-limit) reused by the ledger summary ──────────
function Meter({ label, value, of }: { label: string; value: number; of: number }) {
  const pctv = of > 0 ? Math.min(100, Math.round((value / of) * 100)) : 0;
  return (
    <div className="mini-meter">
      <div className="mini-meter-head">
        <span>{label}</span>
        <span className="muted">{fmtUsd(value)} / {fmtUsd(of)}</span>
      </div>
      <div className="bar"><span style={{ width: `${pctv}%` }} /></div>
    </div>
  );
}
