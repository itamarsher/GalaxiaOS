// Galaxia Command — business objectives → active quests.
//
// A "quest" is one mission objective reframed as a game goal. Each task carries an
// explicit `objective_id` (the CEO tags every dispatched initiative and sub-tasks
// inherit it), so a quest's progress is a direct roll-up of the tasks tagged to
// its objective — no guessing. This is framework-free (no React) and deterministic
// (no Date/Math.random), so the same inputs always yield the same board and the
// page differ can trust id/status transitions to fire FX.

import type { Objective, Task } from "@/lib/api";

// Objective statuses the backend stamps once an objective is fulfilled. We treat
// any of these as "cleared" even if no tagged task remains on screen.
const DONE_STATUSES = new Set(["completed", "complete", "done", "achieved"]);

export type QuestStatus = "active" | "complete";

export interface QuestView {
  id: string;
  title: string;
  rationale: string | null;
  priority: number; // 1..3 rank pips (higher = more urgent)
  status: QuestStatus;
  progress: number; // 0..1
  done: number; // matched tasks settled done
  total: number; // matched tasks seen this cycle
  running: number; // matched tasks in flight right now
  agentIds: string[]; // agents currently working this quest (for graph linkage)
  // The concrete work behind the (often aspirational) objective title, so the
  // board shows what is *actually being done*, not just what's promised.
  activity: string | null; // freshest in-flight task goal, or null when idle
  activities: string[]; // distinct in-flight task goals (for the expanded view)
}

const SETTLED = new Set(["done", "failed"]);
const IN_FLIGHT = new Set(["running", "queued", "waiting_approval", "auditing"]);

/** Rank an objective's `priority` int into 1..3 quest pips. Objectives are stored
 *  priority-ascending (0 = top); we invert to "more pips = more urgent". */
function pips(priority: number, count: number): number {
  if (count <= 1) return 3;
  // Top third → 3 pips, middle → 2, rest → 1.
  const band = priority / Math.max(1, count - 1); // 0..1
  return band < 0.34 ? 3 : band < 0.67 ? 2 : 1;
}

/**
 * Fold the company's objectives + the live task stream into an ordered quest
 * board. Highest-priority quests lead; within a priority band, in-flight quests
 * float above idle ones and cleared quests sink to the bottom.
 */
export function buildQuests(objectives: Objective[], tasks: Task[]): QuestView[] {
  // Group tasks by the objective they were tagged with (newest-first order kept).
  const tasksByObjective = new Map<string, Task[]>();
  for (const t of tasks) {
    if (!t.objective_id) continue;
    const arr = tasksByObjective.get(t.objective_id);
    if (arr) arr.push(t);
    else tasksByObjective.set(t.objective_id, [t]);
  }

  const quests: QuestView[] = objectives.map((obj, i) => {
    let done = 0;
    let total = 0;
    let running = 0;
    const agentIds = new Set<string>();
    // Concrete in-flight work behind this objective. Tasks arrive newest-first, so
    // the first running goal we see is the freshest "happening now"; we keep the
    // full in-flight list (deduped, running before queued) for the expanded view.
    const activities: string[] = [];
    const seenGoals = new Set<string>();
    let activity: string | null = null;
    let activityRank = 0; // running = 2, other in-flight = 1
    for (const t of tasksByObjective.get(obj.id) ?? []) {
      if (SETTLED.has(t.status) || IN_FLIGHT.has(t.status)) total++;
      if (t.status === "done") done++;
      if (IN_FLIGHT.has(t.status)) {
        if (t.agent_id) agentIds.add(t.agent_id);
        if (t.status === "running") running++;
        const goal = t.goal?.trim();
        if (goal && !seenGoals.has(goal)) {
          seenGoals.add(goal);
          activities.push(goal);
        }
        const rank = t.status === "running" ? 2 : 1;
        if (rank > activityRank) {
          activity = goal ?? activity;
          activityRank = rank;
        }
      }
    }
    const backendDone = DONE_STATUSES.has((obj.status ?? "").toLowerCase());
    // A quest is cleared when the backend says so, or when every task tagged to it
    // this cycle has landed done (and at least one did).
    const complete = backendDone || (total > 0 && done === total);
    const progress = backendDone ? 1 : total > 0 ? done / total : 0;
    return {
      id: obj.id,
      title: obj.title,
      rationale: obj.rationale,
      priority: pips(obj.priority ?? i, objectives.length),
      status: complete ? "complete" : "active",
      progress,
      done,
      total,
      running,
      agentIds: [...agentIds],
      activity,
      activities,
    };
  });

  // Stable sort: active first, then more in-flight work, then higher priority.
  return quests
    .map((q, i) => ({ q, i }))
    .sort((a, b) => {
      const ac = a.q.status === "complete" ? 1 : 0;
      const bc = b.q.status === "complete" ? 1 : 0;
      if (ac !== bc) return ac - bc;
      if (a.q.running !== b.q.running) return b.q.running - a.q.running;
      if (a.q.priority !== b.q.priority) return b.q.priority - a.q.priority;
      return a.i - b.i; // preserve backend priority order as the tie-breaker
    })
    .map(({ q }) => q);
}
