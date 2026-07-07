// Galaxia Command — transient FX event queue.
//
// The page's data differ pushes short-lived visual events here (a task settled, a
// lead landed, a level-up); the rAF renderer (render.ts `drawFx`) draws them and
// is the SINGLE owner of expiry — the differ only ever appends. No React state,
// so FX never causes a re-render; timing is `performance.now()`-based like the
// rest of the loop.

export type FxKind =
  | "taskBurst" // a task settled: { x, y, good }
  | "orbLaunch" // a task newly queued/running: { x, y }
  | "leadLand" // a new lead/site: { x, y }
  | "scorePop" // floating +N: { x, y, value, good }
  | "levelUp" // sector standing rose a band: { label }
  | "rankUp" // a droid's rank increased: { x, y }
  | "cycleStart" // a new round began: { x, y } (CEO module)
  | "questNew" // a new quest was posted: { x, y }
  | "questDone" // a quest was cleared: { x, y }
  | "shake"; // screen-shake pulse: { mag }

export interface FxEvent {
  id: number;
  kind: FxKind;
  bornMs: number;
  ttlMs: number;
  data: Record<string, number | string | boolean>;
}

export interface FxQueue {
  events: FxEvent[];
  push: (kind: FxKind, ttlMs: number, data: FxEvent["data"], nowMs: number) => void;
}

const MAX_EVENTS = 40;

export function makeFxQueue(): FxQueue {
  let nextId = 1;
  const q: FxQueue = {
    events: [],
    push(kind, ttlMs, data, nowMs) {
      // Cap the queue so a burst of deltas can never unbound the array; drop the
      // oldest (front) since it's closest to expiring anyway.
      if (q.events.length >= MAX_EVENTS) q.events.shift();
      q.events.push({ id: nextId++, kind, bornMs: nowMs, ttlMs, data });
    },
  };
  return q;
}

// Default lifetimes (ms) per kind — tuned for a snappy, readable pop.
export const FX_TTL: Record<FxKind, number> = {
  taskBurst: 650,
  orbLaunch: 500,
  leadLand: 800,
  scorePop: 1100,
  levelUp: 2200,
  rankUp: 900,
  cycleStart: 1200,
  questNew: 1100,
  questDone: 1600,
  shake: 500,
};
