// Galaxia Command — scene model + business→game mapping.
//
// This module is framework-free (no React, no canvas). It turns the live
// company data (agents, tasks, budget, runway, reputation, sites, decisions)
// into a `SceneModel`: a plain description of what the pixel-art starbase should
// look like. `lib/game/render.ts` draws a SceneModel; `useStationLoop` animates
// it. Keeping the mapping here means the render loop stays dumb and the page
// stays declarative.

import type {
  Agent,
  BudgetView,
  Decision,
  Reputation,
  Runway,
  Site,
  Task,
} from "@/lib/api";

// ── Virtual resolution ──────────────────────────────────────────────────────
// The whole scene is authored in these low-res "virtual units" and blitted up
// with an integer factor (see useStationLoop) so the pixels stay crisp.
export const VW = 320;
export const VH = 180;

// ── Palette ─────────────────────────────────────────────────────────────────
// We read the site's CSS custom properties once so the game shares one signature
// colour set with the rest of the app. getComputedStyle can return "" on the
// very first paint / during SSR, so every entry has a literal fallback that
// matches globals.css.
export interface Palette {
  bg: string;
  bgGlow: string;
  panel: string;
  panel2: string;
  border: string;
  text: string;
  muted: string;
  accent: string;
  accentStrong: string;
  good: string;
  warn: string;
  danger: string;
  onAccent: string;
}

const FALLBACK_PALETTE: Palette = {
  bg: "#0d1320",
  bgGlow: "#161a36",
  panel: "#151d2e",
  panel2: "#1b2438",
  border: "#27324a",
  text: "#e7edf6",
  muted: "#8b99b2",
  accent: "#6366f1",
  accentStrong: "#a5b4fc",
  good: "#34d399",
  warn: "#f5b544",
  danger: "#f87171",
  onAccent: "#ffffff",
};

let cachedPalette: Palette | null = null;

/** Read the brand palette from :root CSS vars, cached after the first good read. */
export function readPalette(): Palette {
  if (cachedPalette) return cachedPalette;
  if (typeof window === "undefined" || typeof getComputedStyle === "undefined") {
    return FALLBACK_PALETTE;
  }
  const cs = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => {
    const raw = cs.getPropertyValue(name).trim();
    return raw || fallback;
  };
  const p: Palette = {
    bg: v("--bg", FALLBACK_PALETTE.bg),
    bgGlow: v("--bg-glow", FALLBACK_PALETTE.bgGlow),
    panel: v("--panel", FALLBACK_PALETTE.panel),
    panel2: v("--panel-2", FALLBACK_PALETTE.panel2),
    border: v("--border", FALLBACK_PALETTE.border),
    text: v("--text", FALLBACK_PALETTE.text),
    muted: v("--muted", FALLBACK_PALETTE.muted),
    accent: v("--accent", FALLBACK_PALETTE.accent),
    accentStrong: v("--accent-strong", FALLBACK_PALETTE.accentStrong),
    good: v("--good", FALLBACK_PALETTE.good),
    warn: v("--warn", FALLBACK_PALETTE.warn),
    danger: v("--danger", FALLBACK_PALETTE.danger),
    onAccent: v("--on-accent", FALLBACK_PALETTE.onAccent),
  };
  // Only cache once we've clearly read real values (accent isn't the fallback by
  // accident — if the var is missing we keep trying on later frames).
  if (cs.getPropertyValue("--accent").trim()) cachedPalette = p;
  return p;
}

// ── Station layout ──────────────────────────────────────────────────────────
// Fixed module slots, one per canonical agent role, arranged around a central
// reactor. Positions/sizes are in virtual units. The Command bridge sits up top;
// support modules ring the core. Unknown/extra agents get deterministic aux
// slots (see buildScene).
export interface Slot {
  label: string;
  short: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

// Core reactor rectangle (drawn behind modules).
export const REACTOR = { x: VW / 2 - 26, y: VH / 2 - 20, w: 52, h: 40 };

export const MODULE_SLOTS: Record<string, Slot> = {
  ceo: { label: "Command Bridge", short: "CMD", x: 130, y: 20, w: 60, h: 26 },
  governance: { label: "Shield Array", short: "SHLD", x: 34, y: 30, w: 52, h: 24 },
  finance: { label: "Reactor Ops", short: "RCTR", x: 234, y: 30, w: 52, h: 24 },
  research: { label: "Science Lab", short: "LAB", x: 20, y: 78, w: 52, h: 24 },
  product: { label: "Fabricator", short: "FAB", x: 248, y: 78, w: 52, h: 24 },
  growth: { label: "Comms Beacon", short: "COMM", x: 34, y: 126, w: 52, h: 24 },
  design: { label: "Design Deck", short: "DSGN", x: 234, y: 126, w: 52, h: 24 },
  data: { label: "Data Vault", short: "DATA", x: 92, y: 146, w: 52, h: 24 },
  auditor: { label: "Audit Ring", short: "AUDT", x: 176, y: 146, w: 52, h: 24 },
  platform: { label: "Platform Bay", short: "PLAT", x: 130, y: 146, w: 52, h: 24 },
};

// Aux slots for overflow agents (custom roles, or duplicate roles). Placed along
// the bottom edge so the core layout stays stable regardless of fleet shape.
const AUX_SLOTS: Slot[] = [
  { label: "Aux Pod α", short: "AUX", x: 8, y: 158, w: 40, h: 18 },
  { label: "Aux Pod β", short: "AUX", x: 272, y: 158, w: 40, h: 18 },
  { label: "Aux Pod γ", short: "AUX", x: 8, y: 104, w: 34, h: 16 },
  { label: "Aux Pod δ", short: "AUX", x: 278, y: 104, w: 34, h: 16 },
  { label: "Aux Pod ε", short: "AUX", x: 8, y: 54, w: 34, h: 16 },
  { label: "Aux Pod ζ", short: "AUX", x: 278, y: 54, w: 34, h: 16 },
];

/** Canonical role → slot, or null when the role has no dedicated module. */
export function roleModule(role: string): Slot | null {
  return MODULE_SLOTS[role] ?? null;
}

// ── Scene view types ────────────────────────────────────────────────────────
export interface ModuleView {
  key: string; // stable id: agentId or `slot:<role>`
  agentId: string | null;
  role: string;
  label: string;
  short: string;
  name: string; // agent name, or role label when empty
  x: number;
  y: number;
  w: number;
  h: number;
  powered: boolean; // agent active (not paused) and station powered
  alert: boolean; // an agent task is waiting for founder approval
  working: boolean; // the agent has a task actively running this cycle
  rankStars: number; // 0..5 from reputation trust
  status: string; // raw agent status (for the roster pill)
  budgetCents: number | null;
}

export interface DroidView {
  moduleKey: string;
  x: number; // droid centre (virtual units)
  y: number;
  powered: boolean;
  rankStars: number;
  bobSeed: number; // per-droid phase so they don't bob in lockstep
}

export type MissionStatus = "running" | "queued" | "done" | "failed" | "waiting_approval";
export interface MissionOrb {
  id: string;
  fromKey: string | null; // module the task belongs to
  status: MissionStatus;
  seed: number; // deterministic phase along its path
}

export interface PlanetView {
  id: string;
  x: number;
  y: number;
  r: number;
  lit: boolean; // deployed site
  leads: number;
  seed: number;
}

export interface ReactorView {
  spentPct: number; // 0..1 of limit
  reservedPct: number; // 0..1 of limit
  burnPerDay: number; // cents/day — drives drip speed
}

export interface SceneModel {
  palette: Palette;
  stationPowered: boolean;
  statusLabel: string; // company status (for the powering-up overlay caption)
  modules: ModuleView[];
  droids: DroidView[];
  missions: MissionOrb[];
  planets: PlanetView[];
  reactor: ReactorView;
  health: number; // 0..100
  roundActive: boolean; // a cycle is running (any active task)
  roundProgress: number; // 0..1 — tasks settled / total seen this round
}

// Rectangles the pointer hit-tester needs (mirrored into the loop's hitRef).
export interface HitModule {
  key: string;
  agentId: string | null;
  x: number;
  y: number;
  w: number;
  h: number;
}

// ── Health / standing ───────────────────────────────────────────────────────
const clamp01 = (n: number) => Math.max(0, Math.min(1, n));

export interface HealthInputs {
  runway: Runway | null;
  tasks: Task[];
  reputation: Reputation[];
  sites: Site[];
  budget: BudgetView | null;
}

/** Company health 0..100 — a weighted blend of runway, delivery, ROI, leads and
 *  budget headroom. Missing signals default to a neutral 0.5 so a fresh company
 *  reads as "middling", never 0. */
export function deriveHealth(inp: HealthInputs): number {
  const days = inp.runway?.projected_days_remaining ?? null;
  const runwayScore = days == null ? 0.5 : clamp01((days - 7) / (60 - 7));

  const done = inp.tasks.filter((t) => t.status === "done").length;
  const failed = inp.tasks.filter((t) => t.status === "failed").length;
  const deliveryScore = done + failed === 0 ? 0.5 : done / (done + failed);

  const roiVals = inp.reputation.map((r) => r.roi).filter((n) => typeof n === "number");
  const roiScore =
    roiVals.length === 0 ? 0.5 : clamp01(roiVals.reduce((a, b) => a + b, 0) / roiVals.length);

  const totalLeads = inp.sites.reduce((a, s) => a + (s.lead_count ?? 0), 0);
  const leadsScore = Math.min(1, totalLeads / 20);

  const b = inp.budget?.budget;
  const budgetScore = b && b.limit_cents ? clamp01(1 - b.spent_cents / b.limit_cents) : 0.5;

  const health =
    0.3 * runwayScore +
    0.25 * deliveryScore +
    0.2 * roiScore +
    0.15 * leadsScore +
    0.1 * budgetScore;
  return Math.round(100 * health);
}

/** Rank the station by health band. Higher health = grander installation. */
export function sectorStanding(health: number): string {
  if (health >= 80) return "Citadel";
  if (health >= 60) return "Starbase";
  if (health >= 40) return "Station";
  return "Outpost";
}

// ── buildScene ──────────────────────────────────────────────────────────────
export interface SceneInputs {
  companyStatus: string | null;
  agents: Agent[];
  tasks: Task[];
  budget: BudgetView | null;
  runway: Runway | null;
  reputation: Reputation[];
  sites: Site[];
}

const MAX_ORBS = 24;

// Deterministic small hash so seeds are stable across polls (no Math.random,
// which would make sprites jitter every rebuild).
function hashSeed(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 0xffffffff;
}

function rankFromReputation(rep: Reputation | undefined): number {
  if (!rep || rep.sample_count <= 0) return 0;
  return Math.max(0, Math.min(5, Math.round((rep.trust ?? 0) * 5)));
}

export function buildScene(inp: SceneInputs): SceneModel {
  const palette = readPalette();
  const stationPowered = inp.companyStatus === "active";

  const repByAgent = new Map(inp.reputation.map((r) => [r.agent_id, r]));

  // Tasks waiting for approval, grouped by agent, so a module can flash an alert.
  const alertAgents = new Set(
    inp.tasks.filter((t) => t.status === "waiting_approval").map((t) => t.agent_id),
  );
  // Agents with a task actively running → their module shows a "working" scan.
  const workingAgents = new Set(
    inp.tasks.filter((t) => t.status === "running").map((t) => t.agent_id),
  );
  // Cycle progress: how many tasks have settled out of everything seen this round.
  const settledCount = inp.tasks.filter(
    (t) => t.status === "done" || t.status === "failed",
  ).length;
  const activeCount = inp.tasks.filter((t) =>
    ["queued", "running", "waiting_approval", "auditing"].includes(t.status),
  ).length;
  const totalSeen = settledCount + activeCount;
  const roundActive = activeCount > 0;
  const roundProgress = totalSeen > 0 ? settledCount / totalSeen : 0;

  // Assign agents to slots: canonical role slot if free, else an aux slot.
  const usedRoleSlots = new Set<string>();
  const modules: ModuleView[] = [];
  let auxIdx = 0;

  for (const a of inp.agents) {
    let slot: Slot | null = null;
    const canonical = MODULE_SLOTS[a.role];
    if (canonical && !usedRoleSlots.has(a.role)) {
      usedRoleSlots.add(a.role);
      slot = canonical;
    } else {
      slot = AUX_SLOTS[auxIdx % AUX_SLOTS.length];
      auxIdx++;
    }
    const rep = repByAgent.get(a.id);
    const paused = a.status === "paused";
    modules.push({
      key: a.id,
      agentId: a.id,
      role: a.role,
      label: slot.label,
      short: slot.short,
      name: a.name || slot.label,
      x: slot.x,
      y: slot.y,
      w: slot.w,
      h: slot.h,
      powered: stationPowered && !paused,
      alert: alertAgents.has(a.id),
      working: stationPowered && !paused && workingAgents.has(a.id),
      rankStars: rankFromReputation(rep),
      status: a.status,
      budgetCents: a.monthly_budget_cents,
    });
  }

  // When there are no agents yet (draft company), still show the canonical shells
  // dim so the station reads as "under construction" rather than empty space.
  if (modules.length === 0) {
    for (const [role, slot] of Object.entries(MODULE_SLOTS)) {
      modules.push({
        key: `slot:${role}`,
        agentId: null,
        role,
        label: slot.label,
        short: slot.short,
        name: slot.label,
        x: slot.x,
        y: slot.y,
        w: slot.w,
        h: slot.h,
        powered: false,
        alert: false,
        working: false,
        rankStars: 0,
        status: "offline",
        budgetCents: null,
      });
    }
  }

  const moduleByKey = new Map(modules.map((m) => [m.key, m]));

  // One droid per module, centred, bobbing on its own phase.
  const droids: DroidView[] = modules.map((m) => ({
    moduleKey: m.key,
    x: m.x + m.w / 2,
    y: m.y + m.h + 6,
    powered: m.powered,
    rankStars: m.rankStars,
    bobSeed: hashSeed(m.key),
  }));

  // Active tasks become mission orbs (cap for perf). Map each to its agent's
  // module so the orb can travel module→bridge.
  const liveTasks = inp.tasks
    .filter((t) => ["running", "queued", "waiting_approval"].includes(t.status))
    .slice(0, MAX_ORBS);
  const missions: MissionOrb[] = liveTasks.map((t) => {
    const mod = inp.agents.some((a) => a.id === t.agent_id)
      ? modules.find((m) => m.agentId === t.agent_id)
      : undefined;
    return {
      id: t.id,
      fromKey: mod?.key ?? null,
      status: t.status as MissionStatus,
      seed: hashSeed(t.id),
    };
  });

  // Sites become planets docking around the station's lower orbit.
  const planets: PlanetView[] = inp.sites.slice(0, 6).map((s, i) => {
    const seed = hashSeed(s.id);
    const spread = inp.sites.length > 1 ? i / (Math.min(inp.sites.length, 6) - 1 || 1) : 0.5;
    return {
      id: s.id,
      x: 40 + spread * (VW - 80),
      y: VH - 14 + (seed - 0.5) * 6,
      r: 3 + Math.min(4, Math.floor((s.lead_count ?? 0) / 3)),
      lit: s.status === "published" || !!s.deployment_url,
      leads: s.lead_count ?? 0,
      seed,
    };
  });

  const b = inp.budget?.budget;
  const reactor: ReactorView = {
    spentPct: b && b.limit_cents ? clamp01(b.spent_cents / b.limit_cents) : 0,
    reservedPct: b && b.limit_cents ? clamp01(b.reserved_cents / b.limit_cents) : 0,
    burnPerDay: inp.runway?.burn_rate_cents_per_day ?? 0,
  };

  const health = deriveHealth({
    runway: inp.runway,
    tasks: inp.tasks,
    reputation: inp.reputation,
    sites: inp.sites,
    budget: inp.budget,
  });

  // Keep moduleByKey referenced (droids already derive from modules); nothing
  // else needed — return the assembled scene.
  void moduleByKey;

  return {
    palette,
    stationPowered,
    statusLabel: inp.companyStatus ?? "—",
    modules,
    droids,
    missions,
    planets,
    reactor,
    health,
    roundActive,
    roundProgress,
  };
}

/** Hit rectangles for the interactive modules (only those bound to an agent). */
export function hitModules(scene: SceneModel): HitModule[] {
  return scene.modules
    .filter((m) => m.agentId != null)
    .map((m) => ({ key: m.key, agentId: m.agentId, x: m.x, y: m.y, w: m.w, h: m.h }));
}

/** Centre of a module (or the agent's module) in virtual units, for FX anchoring.
 *  Falls back to the reactor core when the key isn't found. */
export function moduleAnchor(scene: SceneModel, key: string | null): { x: number; y: number } {
  const m = key ? scene.modules.find((mm) => mm.key === key || mm.agentId === key) : null;
  if (m) return { x: m.x + m.w / 2, y: m.y + m.h / 2 };
  return { x: REACTOR.x + REACTOR.w / 2, y: REACTOR.y + REACTOR.h / 2 };
}

/** Anchor for a site/planet by id (for lead-landing FX). */
export function planetAnchor(scene: SceneModel, siteId: string): { x: number; y: number } {
  const pl = scene.planets.find((p) => p.id === siteId);
  if (pl) return { x: pl.x, y: pl.y };
  return { x: VW / 2, y: VH - 14 };
}
