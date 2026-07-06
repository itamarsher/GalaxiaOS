"use client";

// Galaxia Command — the "Advance cycle" control (the game's round trigger).
//
// Triggers one real business cycle. Its label/disabled state comes from the
// derived round phase (a cycle may already be running — continuous mode loops on
// its own) plus the backend cycle status, so it never stacks a parallel run.

import { useState } from "react";
import { api } from "@/lib/api";
import type { RoundPhase } from "@/lib/game/round";

const BLOCK_LABEL: Record<string, string> = {
  already_running: "Cycle in progress…",
  not_active: "Launch the company first",
  insufficient_budget: "Out of budget",
  spend_breaker: "Spending paused",
  no_ceo: "No CEO aboard",
};

export function AdvanceButton({
  companyId,
  phase,
  canStart,
  statusReason,
  onAdvanced,
}: {
  companyId: string;
  phase: RoundPhase;
  canStart: boolean;
  statusReason: string; // from GET /cycle when idle & blocked
  onAdvanced: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const running = phase !== "idle" && phase !== "settled";
  const disabled = busy || running || !canStart;

  const label = busy
    ? "Dispatching…"
    : running
      ? "Cycle in progress…"
      : canStart
        ? "▶ Advance cycle"
        : BLOCK_LABEL[statusReason] ?? "Cycle unavailable";

  const advance = async () => {
    setBusy(true);
    setNote(null);
    try {
      const res = await api.advanceCycle(companyId);
      if (!res.started && res.reason !== "already_running") {
        setNote(BLOCK_LABEL[res.reason] ?? res.reason);
      }
      onAdvanced();
    } catch (e) {
      setNote(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="advance-wrap">
      <button className="advance-btn" disabled={disabled} onClick={advance}>
        {label}
      </button>
      {note && <span className="advance-note muted">{note}</span>}
    </div>
  );
}
