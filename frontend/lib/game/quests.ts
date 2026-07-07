// Galaxia Command — business objectives → active quests.
//
// A "quest" is one mission objective reframed as a game goal. Objectives carry no
// explicit task foreign key (see backend app/api/decisions.py), so — exactly like
// the founder decision inbox does server-side — we link each objective to the
// live tasks whose goals share the most distinctive words with it, and read a
// quest's progress off those matched tasks. This is framework-free (no React) and
// deterministic (no Date/Math.random), so the same inputs always yield the same
// board and the page differ can trust id/status transitions to fire FX.

import type { Objective, Task } from "@/lib/api";

// Objective statuses the backend may stamp once an objective is fulfilled. We
// treat any of these as "cleared" even if no matched task remains on screen.
const DONE_STATUSES = new Set(["completed", "complete", "done", "achieved"]);

// Words too generic to signal which objective a task belongs to — mirrors the
// backend stop-list so the client links quests the same way the server links
// decisions to objectives.
const STOPWORDS = new Set(
  `the and for with that this from your you our are will into them they then than
   have has had who what when where which while about over under above below
   company business mission objective objectives plan agent agents task work
   initiative initiatives founder approve approval budget spend decision goal
   launch build make create run running first`.split(/\s+/),
);

function keywords(...texts: (string | null | undefined)[]): Set<string> {
  const words = new Set<string>();
  for (const text of texts) {
    for (const raw of (text ?? "").toLowerCase().replace(/\//g, " ").split(/\s+/)) {
      const token = raw.replace(/[^a-z0-9]/g, "");
      if (token.length >= 4 && !STOPWORDS.has(token)) words.add(token);
    }
  }
  return words;
}

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
  // Pre-key every task's goal once.
  const taskKeys = tasks.map((t) => ({ t, kw: keywords(t.goal) }));

  const quests: QuestView[] = objectives.map((obj, i) => {
    const okw = keywords(obj.title, obj.rationale);
    let done = 0;
    let total = 0;
    let running = 0;
    const agentIds = new Set<string>();
    for (const { t, kw } of taskKeys) {
      let overlap = 0;
      for (const w of kw) if (okw.has(w)) overlap++;
      if (overlap < 2) continue; // weak coincidence — not this quest's work
      if (SETTLED.has(t.status) || IN_FLIGHT.has(t.status)) total++;
      if (t.status === "done") done++;
      if (IN_FLIGHT.has(t.status)) {
        if (t.agent_id) agentIds.add(t.agent_id);
        if (t.status === "running") running++;
      }
    }
    const backendDone = DONE_STATUSES.has((obj.status ?? "").toLowerCase());
    // A quest is cleared when the backend says so, or when every task we linked
    // to it this cycle has landed done (and at least one did).
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
