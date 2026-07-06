"use client";

// Galaxia Command — DOM HUD overlays.
//
// The canvas is a decorative, animated backdrop; every legible or interactive
// surface lives here in the DOM so it's crisp, styleable, and accessible. All
// components reuse the app's existing global CSS classes (.card, .bar, .status,
// .btnrow, .decision-panel, .pill) plus a small `Galaxia Command` block added to
// globals.css.

import {
  fmtUsd,
  statusLabel,
  type BudgetView,
  type Decision,
  type Runway,
} from "@/lib/api";
import { type ModuleView } from "@/lib/game/scene";
import { levelFromScore } from "@/lib/game/score";
import { phaseLabel, type RoundState } from "@/lib/game/round";
import { SwipeDeck } from "./SwipeDeck";

// ── Cycle progress: live phase + task progress while a round runs ─────────────
export function CycleProgress({ round }: { round: RoundState }) {
  const running = round.phase !== "idle" && round.phase !== "settled";
  const pct = Math.round(round.progress * 100);
  const { counts } = round;
  return (
    <div className={`cycle-strip${running ? " active" : ""}`}>
      <div className="cycle-strip-head">
        <span className="step" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {running && <span className="cycle-spinner" aria-hidden />}
          {phaseLabel(round.phase)}
        </span>
        <span className="muted" style={{ fontSize: 12 }}>
          {round.total > 0 ? `${round.settled}/${round.total} tasks` : "no tasks yet"}
        </span>
      </div>
      {/* Determinate progress: settled / total. Striped while active. */}
      <div className="bar cycle-bar">
        <span
          className={running ? "cycle-fill" : ""}
          style={{ width: `${Math.max(running ? 4 : 0, pct)}%` }}
        />
      </div>
      <div className="cycle-counts">
        <span className="cycle-chip run" aria-label={`${counts.running} running`}>
          ● {counts.running} running
        </span>
        <span className="cycle-chip queue" aria-label={`${counts.queued} queued`}>
          {counts.queued} queued
        </span>
        <span className="cycle-chip done" aria-label={`${counts.done} done`}>
          {counts.done} done
        </span>
        {counts.failed > 0 && (
          <span className="cycle-chip fail" aria-label={`${counts.failed} failed`}>
            {counts.failed} failed
          </span>
        )}
        {counts.waiting > 0 && (
          <span className="cycle-chip wait" aria-label={`${counts.waiting} awaiting you`}>
            {counts.waiting} awaiting you
          </span>
        )}
      </div>
    </div>
  );
}

// ── Captain's Console: the decision inbox as a swipeable order deck ───────────
export function CaptainsConsole({
  decisions,
  onResolved,
}: {
  decisions: Decision[];
  onResolved: () => void;
}) {
  const pending = decisions.filter((d) => d.status === "pending" || d.status === "waiting_approval");
  const alert = pending.length > 0;
  return (
    <div className={`card${alert ? " console-alert" : ""}`}>
      <div className="step" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {alert && <span className="dot" style={{ background: "var(--danger)" }} />}
        <span>Captain&apos;s Console{alert ? ` · ${pending.length} awaiting orders` : ""}</span>
      </div>
      <SwipeDeck decisions={decisions} onResolved={onResolved} />
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

// ── Level / XP / score / streak — the progression meter ───────────────────────
export function ScorePanel({
  health,
  score,
  streak,
}: {
  health: number;
  score: number;
  streak: number;
}) {
  const { level, label, intoPct } = levelFromScore(score, health);
  const cls = health >= 60 ? "good" : health >= 40 ? "warn" : "danger";
  return (
    <div className="gauge">
      <div className="gauge-head">
        <span className="step">Command level</span>
        <span className={`status ${cls === "good" ? "active" : cls === "warn" ? "paused" : "failed"}`}>
          {label}
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, margin: "4px 0" }}>
        <span style={{ fontSize: 30, fontWeight: 800, letterSpacing: "-0.02em" }}>Lv {level}</span>
        <span className="muted">· {score.toLocaleString()} pts</span>
        {streak > 1 && (
          <span className="streak-pill" aria-label={`${streak} good cycles in a row`}>
            🔥 ×{streak}
          </span>
        )}
      </div>
      {/* XP bar toward the next level */}
      <div className="bar">
        <span
          style={{
            width: `${Math.max(3, intoPct)}%`,
            background: "linear-gradient(90deg, var(--accent), var(--accent-strong))",
          }}
        />
      </div>
      <div className="kv" style={{ marginTop: 8 }}>
        <span className="muted">Command rating</span>
        <span>{health} / 100</span>
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
