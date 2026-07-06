// Galaxia Command — score, XP, levels and streaks.
//
// Everything here is DERIVED from live company data (health, tasks, leads,
// reputation) so it survives reloads without a server round-trip. Only the streak
// and "last seen" markers live in localStorage — they're about the player's
// session continuity, not company truth.

import type { Reputation, Site } from "@/lib/api";
import { sectorStanding, type SceneModel } from "./scene";
import type { RoundCounts } from "./round";

// ── Career score & levels (stable across reloads) ─────────────────────────────
/** A stable "career" score derived only from current live state. */
export function totalScore(
  health: number,
  doneTasks: number,
  totalLeads: number,
  reputation: Reputation[],
): number {
  const rankStars = reputation.reduce(
    (sum, r) => sum + (r.sample_count > 0 ? Math.round((r.trust ?? 0) * 5) : 0),
    0,
  );
  return Math.max(0, health * 10 + doneTasks * 3 + totalLeads * 4 + rankStars * 20);
}

const LEVEL_K = 150; // score per level² — level = floor(sqrt(score / K))

export interface LevelInfo {
  level: number;
  label: string; // sector-standing flavour band
  intoPct: number; // 0..100 progress within the current level
}

export function levelFromScore(total: number, health: number): LevelInfo {
  const level = Math.floor(Math.sqrt(total / LEVEL_K));
  const floorScore = level * level * LEVEL_K;
  const nextScore = (level + 1) * (level + 1) * LEVEL_K;
  const intoPct = nextScore > floorScore
    ? Math.round(((total - floorScore) / (nextScore - floorScore)) * 100)
    : 0;
  return { level, label: sectorStanding(health), intoPct: Math.max(0, Math.min(100, intoPct)) };
}

// ── Per-round score (for the floating +N pop) ─────────────────────────────────
/** Score for a just-settled round from its real deltas. */
export function roundScore(counts: RoundCounts, leadsGained: number, deltaHealth: number): number {
  return Math.round(counts.done * 10 - counts.failed * 6 + leadsGained * 5 + deltaHealth * 2);
}

/** A round is "good" (streak-eligible) if it delivered and nothing failed. */
export function isGoodRound(counts: RoundCounts): boolean {
  return counts.failed === 0 && counts.done > 0;
}

/** Combo multiplier from the current streak (caps at ×1.5). */
export function comboMultiplier(streak: number): number {
  return 1 + Math.min(streak, 5) * 0.1;
}

// ── Session persistence (localStorage) ────────────────────────────────────────
export interface GameProgress {
  streak: number;
  lastSeenLevel: number;
  lastSeenStanding: string;
  bestScore: number;
}

const DEFAULT_PROGRESS: GameProgress = {
  streak: 0,
  lastSeenLevel: 0,
  lastSeenStanding: "Outpost",
  bestScore: 0,
};

function key(companyId: string): string {
  return `galaxia:${companyId}`;
}

export function loadProgress(companyId: string): GameProgress {
  if (typeof window === "undefined") return { ...DEFAULT_PROGRESS };
  try {
    const raw = window.localStorage.getItem(key(companyId));
    if (!raw) return { ...DEFAULT_PROGRESS };
    return { ...DEFAULT_PROGRESS, ...(JSON.parse(raw) as Partial<GameProgress>) };
  } catch {
    return { ...DEFAULT_PROGRESS };
  }
}

export function saveProgress(companyId: string, p: GameProgress): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key(companyId), JSON.stringify(p));
  } catch {
    /* storage full / disabled — non-fatal, score just won't persist */
  }
}

/** Convenience: total leads across a company's sites. */
export function totalLeads(sites: Site[]): number {
  return sites.reduce((a, s) => a + (s.lead_count ?? 0), 0);
}

/** Convenience: the current standing for a scene (for level-up detection). */
export function standingFor(scene: SceneModel): string {
  return sectorStanding(scene.health);
}
