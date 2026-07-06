// Galaxia Command — the "round" state machine.
//
// A round == one business cycle: a CEO-rooted run that dispatches initiatives to
// the fleet. The backend runs one cycle at a time per company (the cron and
// continuous mode both guard against stacking), so we can frame the current round
// from the live task stream alone — no separate round record needed.
//
// Pure and framework-free: `deriveRound(tasks, prevRootKey)` folds the live task
// list into a phase + counts. The page keeps `prevRootKey` in a ref; when it
// changes, a new round has begun (drives the "cycle start" FX).

import type { Task } from "@/lib/api";

export type RoundPhase = "idle" | "dispatching" | "working" | "resolving" | "settled";

export interface RoundCounts {
  queued: number;
  running: number;
  waiting: number; // waiting_approval
  auditing: number;
  done: number;
  failed: number;
}

export interface RoundState {
  phase: RoundPhase;
  rootKey: string | null; // root_run_id of the current round (fallback: newest depth-0 task id)
  counts: RoundCounts;
  activeTotal: number; // queued + running + waiting + auditing
  settled: number; // done + failed
  total: number; // settled + activeTotal (tasks seen this round)
  progress: number; // 0..1 — settled / total
}

const ACTIVE = new Set(["queued", "running", "waiting_approval", "auditing"]);

function emptyCounts(): RoundCounts {
  return { queued: 0, running: 0, waiting: 0, auditing: 0, done: 0, failed: 0 };
}

/** Pick the round's root key: the root_run_id of the newest active task (tasks
 *  arrive newest-first), else the newest depth-0 CEO task id, else null. */
function pickRootKey(tasks: Task[]): string | null {
  const activeWithRoot = tasks.find((t) => ACTIVE.has(t.status) && t.root_run_id);
  if (activeWithRoot?.root_run_id) return activeWithRoot.root_run_id;
  const ceo = tasks.find((t) => t.depth === 0);
  return ceo?.root_run_id ?? ceo?.id ?? null;
}

export function deriveRound(tasks: Task[]): RoundState {
  const counts = emptyCounts();
  for (const t of tasks) {
    switch (t.status) {
      case "queued": counts.queued++; break;
      case "running": counts.running++; break;
      case "waiting_approval": counts.waiting++; break;
      case "auditing": counts.auditing++; break;
      case "done": counts.done++; break;
      case "failed": counts.failed++; break;
      default: break;
    }
  }
  const activeTotal = counts.queued + counts.running + counts.waiting + counts.auditing;
  const settled = counts.done + counts.failed;
  const total = settled + activeTotal;
  const progress = total > 0 ? settled / total : 0;
  const rootKey = pickRootKey(tasks);

  let phase: RoundPhase;
  if (activeTotal === 0) {
    // Nothing live: "settled" if the last round left visible outcomes, else idle.
    phase = counts.done + counts.failed > 0 ? "settled" : "idle";
  } else if (counts.running + counts.queued === 0 && counts.waiting + counts.auditing > 0) {
    phase = "resolving"; // only founder-gated / audit work remains
  } else {
    // The depth-0 CEO task running with no functional work yet = dispatching.
    const ceoRunning = tasks.some((t) => t.depth === 0 && t.status === "running");
    const functionalActive = tasks.some(
      (t) => t.depth > 0 && (t.status === "running" || t.status === "queued"),
    );
    phase = ceoRunning && !functionalActive ? "dispatching" : "working";
  }

  return { phase, rootKey, counts, activeTotal, settled, total, progress };
}

/** Human label for the round phase (for the aria-live announcer + button). */
export function phaseLabel(phase: RoundPhase): string {
  switch (phase) {
    case "idle": return "Idle";
    case "dispatching": return "Dispatching initiatives";
    case "working": return "Crew working";
    case "resolving": return "Awaiting your orders";
    case "settled": return "Cycle complete";
  }
}
