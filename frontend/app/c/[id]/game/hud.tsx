"use client";

// Galaxia Command — DOM HUD overlays.
//
// The canvas is a decorative, animated backdrop; every legible or interactive
// surface lives here in the DOM so it's crisp, styleable, and accessible. All
// components reuse the app's existing global CSS classes (.card, .bar, .status,
// .btnrow, .decision-panel, .pill) plus a small `Galaxia Command` block added to
// globals.css.

import { useState } from "react";
import {
  api,
  decisionKindLabel,
  fmtUsd,
  statusLabel,
  type BudgetView,
  type Decision,
  type Runway,
} from "@/lib/api";
import { Markdown } from "@/lib/markdown";
import { sectorStanding, type ModuleView } from "@/lib/game/scene";

// ── Captain's Console: the decision inbox as red-alert command orders ─────────
export function CaptainsConsole({
  companyId,
  decisions,
  onResolved,
}: {
  companyId: string;
  decisions: Decision[];
  onResolved: () => void;
}) {
  void companyId;
  const pending = decisions.filter((d) => d.status === "pending" || d.status === "waiting_approval");
  const alert = pending.length > 0;
  return (
    <div className={`card${alert ? " console-alert" : ""}`}>
      <div className="step" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {alert && <span className="dot" style={{ background: "var(--danger)" }} />}
        <span>Captain&apos;s Console{alert ? ` · ${pending.length} awaiting orders` : ""}</span>
      </div>
      {pending.length === 0 ? (
        <p className="muted" style={{ marginTop: 10 }}>All clear, Captain. No orders pending.</p>
      ) : (
        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 10 }}>
          {pending.map((d) => (
            <ConsoleOrder key={d.id} decision={d} onResolved={onResolved} />
          ))}
        </div>
      )}
    </div>
  );
}

function ConsoleOrder({ decision, onResolved }: { decision: Decision; onResolved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const resolve = async (approve: boolean) => {
    setBusy(true);
    try {
      if (approve) await api.approveDecision(decision.id);
      else await api.rejectDecision(decision.id);
      setDone(true); // optimistically drop the card
      onResolved();
    } catch {
      setBusy(false); // let them retry on failure
    }
  };

  if (done) return null;

  return (
    <div className="decision-panel">
      <div className="decision-kind">
        {decisionKindLabel(decision.kind)}
        {decision.agent_name ? ` · ${decision.agent_name}` : ""}
        {decision.agent_role ? ` (${decision.agent_role})` : ""}
      </div>
      <Markdown className="decision-note">{decision.summary}</Markdown>
      <div className="btnrow">
        <button disabled={busy} onClick={() => resolve(true)}>
          {busy ? "…" : "Approve order"}
        </button>
        <button className="ghost" disabled={busy} onClick={() => resolve(false)}>
          Reject
        </button>
      </div>
    </div>
  );
}

// ── Life-support gauge (runway) ───────────────────────────────────────────────
export function RunwayGauge({ runway }: { runway: Runway | null }) {
  const days = runway?.projected_days_remaining ?? null;
  // Colour band: <14d danger, <30d warn, else good.
  const cls = days == null ? "" : days < 14 ? "danger" : days < 30 ? "warn" : "good";
  // Bar fills toward "full life support" at 60+ days.
  const pct = days == null ? 0 : Math.max(4, Math.min(100, (days / 60) * 100));
  return (
    <div className="gauge">
      <div className="gauge-head">
        <span className="step">Life support</span>
        <span className={`status ${cls === "good" ? "active" : cls === "warn" ? "paused" : cls === "danger" ? "failed" : ""}`}>
          {days == null ? "—" : `${days}d`}
        </span>
      </div>
      <div className="bar">
        <span
          style={{
            width: `${pct}%`,
            background:
              cls === "danger"
                ? "var(--danger)"
                : cls === "warn"
                  ? "var(--warn)"
                  : "linear-gradient(90deg, var(--accent), var(--good))",
          }}
        />
      </div>
      <div className="kv" style={{ marginTop: 8 }}>
        <span className="muted">Balance</span>
        <span>{fmtUsd(runway?.balance_cents)}</span>
      </div>
      <div className="kv">
        <span className="muted">Burn / day</span>
        <span>{fmtUsd(runway?.burn_rate_cents_per_day ?? 0)}</span>
      </div>
    </div>
  );
}

// ── Reactor gauge (budget) ────────────────────────────────────────────────────
export function ReactorGauge({ budget }: { budget: BudgetView | null }) {
  const b = budget?.budget;
  const spentPct = b && b.limit_cents ? Math.min(100, (b.spent_cents / b.limit_cents) * 100) : 0;
  const reservedPct = b && b.limit_cents ? Math.min(100, (b.reserved_cents / b.limit_cents) * 100) : 0;
  return (
    <div className="gauge">
      <div className="gauge-head">
        <span className="step">Reactor core</span>
        <span className="muted" style={{ fontSize: 12 }}>
          {b ? `${fmtUsd(b.spent_cents)} / ${fmtUsd(b.limit_cents)}` : "—"}
        </span>
      </div>
      <div className="bar" style={{ position: "relative" }}>
        <span style={{ width: `${spentPct}%` }} />
        {/* Reserved sits as a lighter overlay beyond spent. */}
        <span
          style={{
            position: "absolute",
            left: `${spentPct}%`,
            top: 0,
            height: "100%",
            width: `${reservedPct}%`,
            background: "var(--accent-soft)",
          }}
        />
      </div>
      <div className="kv" style={{ marginTop: 8 }}>
        <span className="muted">Reserved</span>
        <span>{b ? fmtUsd(b.reserved_cents) : "—"}</span>
      </div>
    </div>
  );
}

// ── Score / sector standing ───────────────────────────────────────────────────
export function ScorePanel({ health }: { health: number }) {
  const standing = sectorStanding(health);
  const cls = health >= 60 ? "good" : health >= 40 ? "warn" : "danger";
  return (
    <div className="gauge">
      <div className="gauge-head">
        <span className="step">Sector standing</span>
        <span className={`status ${cls === "good" ? "active" : cls === "warn" ? "paused" : "failed"}`}>
          {standing}
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, margin: "6px 0 4px" }}>
        <span style={{ fontSize: 30, fontWeight: 800, letterSpacing: "-0.02em" }}>{health}</span>
        <span className="muted">/ 100 command rating</span>
      </div>
      <div className="bar">
        <span
          style={{
            width: `${Math.max(3, health)}%`,
            background:
              cls === "good"
                ? "linear-gradient(90deg, var(--accent), var(--good))"
                : cls === "warn"
                  ? "var(--warn)"
                  : "var(--danger)",
          }}
        />
      </div>
    </div>
  );
}

// ── Crew roster: accessible DOM mirror of the canvas modules ──────────────────
export function CrewRoster({
  modules,
  onToggle,
  busyKey,
}: {
  modules: ModuleView[];
  onToggle: (m: ModuleView) => void;
  busyKey: string | null;
}) {
  const crewed = modules.filter((m) => m.agentId != null);
  return (
    <div className="card">
      <div className="step">Crew roster</div>
      {crewed.length === 0 ? (
        <p className="muted" style={{ marginTop: 10 }}>No crew aboard yet — the station is powering up.</p>
      ) : (
        <div style={{ marginTop: 8 }}>
          {crewed.map((m) => (
            <div key={m.key} className="exprow" style={{ cursor: "default" }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <strong style={{ fontSize: 14 }}>{m.name}</strong>
                  <span className="rank-stars" aria-label={`${m.rankStars} of 5 rank`}>
                    {"★".repeat(m.rankStars)}
                    <span className="rank-dim">{"★".repeat(5 - m.rankStars)}</span>
                  </span>
                </div>
                <div className="muted" style={{ fontSize: 12 }}>
                  {m.label} · {m.role}
                  {m.budgetCents != null ? ` · ${fmtUsd(m.budgetCents)}/mo` : ""}
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "0 0 auto" }}>
                <span className={`status ${m.status}`}>{statusLabel(m.status)}</span>
                <button
                  className="ghost"
                  style={{ marginTop: 0, padding: "6px 10px", fontSize: 12 }}
                  disabled={busyKey === m.key}
                  onClick={() => onToggle(m)}
                >
                  {busyKey === m.key ? "…" : m.status === "paused" ? "Power on" : "Power off"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Legend ────────────────────────────────────────────────────────────────────
export function Legend() {
  const items: [string, string][] = [
    ["var(--accent)", "Mission running"],
    ["var(--muted)", "Mission queued"],
    ["var(--good)", "Mission done"],
    ["var(--warn)", "Awaiting approval"],
    ["var(--danger)", "Mission failed / alert"],
  ];
  return (
    <div className="card">
      <div className="step">Legend</div>
      <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
        {items.map(([c, label]) => (
          <div key={label} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: c, flex: "0 0 auto" }} />
            <span className="muted">{label}</span>
          </div>
        ))}
      </div>
      <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
        Tap a lit module (or use the roster) to power a crew droid on or off. The reactor core is your
        budget; life support is your runway.
      </p>
    </div>
  );
}

// ── Module tooltip (desktop hover) ────────────────────────────────────────────
export function ModuleTooltip({ module, left, top }: { module: ModuleView; left: number; top: number }) {
  return (
    <div className="mod-tooltip" style={{ left, top }}>
      <strong>{module.name}</strong>
      <div className="muted" style={{ fontSize: 12 }}>{module.label}</div>
      <div style={{ marginTop: 4 }}>
        <span className={`status ${module.status}`}>{statusLabel(module.status)}</span>
      </div>
      {module.rankStars > 0 && (
        <div className="rank-stars" style={{ marginTop: 4 }}>
          {"★".repeat(module.rankStars)}
          <span className="rank-dim">{"★".repeat(5 - module.rankStars)}</span>
        </div>
      )}
    </div>
  );
}

// ── Module action sheet (touch tap) ───────────────────────────────────────────
export function ModuleSheet({
  module,
  busy,
  onToggle,
  onClose,
}: {
  module: ModuleView;
  busy: boolean;
  onToggle: (m: ModuleView) => void;
  onClose: () => void;
}) {
  return (
    <div className="mod-sheet-scrim" onClick={onClose}>
      <div className="mod-sheet card" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <strong>{module.name}</strong>
            <div className="muted" style={{ fontSize: 12 }}>{module.label} · {module.role}</div>
          </div>
          <span className={`status ${module.status}`}>{statusLabel(module.status)}</span>
        </div>
        {module.rankStars > 0 && (
          <div className="rank-stars" style={{ marginTop: 6 }}>
            {"★".repeat(module.rankStars)}
            <span className="rank-dim">{"★".repeat(5 - module.rankStars)}</span>
          </div>
        )}
        <div className="btnrow" style={{ marginTop: 12 }}>
          <button disabled={busy} onClick={() => onToggle(module)}>
            {busy ? "…" : module.status === "paused" ? "Power module on" : "Power module off"}
          </button>
          <button className="ghost" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
