// Galaxia Command — pure canvas drawing.
//
// Every function here draws into a low-res offscreen buffer in virtual units
// (VW×VH). No React, no DOM. Motion is driven by an incoming `timeMs` so the
// scene animates independently of React renders. Colours come from the scene's
// palette (the site's CSS vars) so the game shares the app's signature look.
//
// Sprites are authored as string arrays where each char indexes a small colour
// ramp — this keeps everything in-repo and in-palette with zero binary assets.

import type { FxEvent, FxQueue } from "./fx";
import {
  REACTOR,
  VH,
  VW,
  type MissionOrb,
  type ModuleView,
  type Palette,
  type PlanetView,
  type SceneModel,
} from "./scene";

// A stable starfield: generated once (seeded) so stars don't teleport each frame.
export interface Star {
  x: number;
  y: number;
  layer: number; // 0 far … 2 near (parallax + brightness)
  twinkle: number;
}

export function makeStarfield(count: number): Star[] {
  // Deterministic LCG so the field is identical across reloads (no Math.random).
  let s = 987654321;
  const rnd = () => {
    s = (Math.imul(s, 1103515245) + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
  const stars: Star[] = [];
  for (let i = 0; i < count; i++) {
    stars.push({
      x: Math.floor(rnd() * VW),
      y: Math.floor(rnd() * VH),
      layer: Math.floor(rnd() * 3),
      twinkle: rnd(),
    });
  }
  return stars;
}

// Blend two hex colours (#rrggbb) by t∈[0,1]. Used for dimming/glows.
function mix(a: string, b: string, t: number): string {
  const pa = hexToRgb(a);
  const pb = hexToRgb(b);
  if (!pa || !pb) return a;
  const r = Math.round(pa[0] + (pb[0] - pa[0]) * t);
  const g = Math.round(pa[1] + (pb[1] - pa[1]) * t);
  const bl = Math.round(pa[2] + (pb[2] - pa[2]) * t);
  return `rgb(${r},${g},${bl})`;
}

function hexToRgb(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) {
    // Accept rgb() passthrough by returning null → callers fall back to base.
    return null;
  }
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

// Snap to whole virtual pixels — the pixel-art motion aesthetic.
const px = Math.floor;

// ── Top-level ────────────────────────────────────────────────────────────────
// Returns a shake offset (virtual units) the loop applies to the blit so failures
// and level-ups jolt the whole scene.
export function renderStation(
  ctx: CanvasRenderingContext2D,
  scene: SceneModel,
  stars: Star[],
  timeMs: number,
  reducedMotion: boolean,
  fx: FxQueue | null,
): { shakeX: number; shakeY: number } {
  const p = scene.palette;
  const t = reducedMotion ? 0 : timeMs;

  // Background: base + a soft central glow echoing the site's hero gradient.
  ctx.fillStyle = p.bg;
  ctx.fillRect(0, 0, VW, VH);
  drawGlow(ctx, p);
  drawStarfield(ctx, stars, p, t, reducedMotion);

  drawReactor(ctx, scene, t);
  drawTrusses(ctx, scene);
  for (const m of scene.modules) drawModule(ctx, m, p, t);
  drawPlanets(ctx, scene.planets, p, t);
  for (const d of scene.droids) drawDroid(ctx, d, p, t);
  for (const orb of scene.missions) drawMissionOrb(ctx, orb, scene, p, t);

  if (!scene.stationPowered) drawPoweringUp(ctx, scene, p, t);

  return fx ? drawFx(ctx, fx, p, timeMs, reducedMotion) : { shakeX: 0, shakeY: 0 };
}

function drawGlow(ctx: CanvasRenderingContext2D, p: Palette) {
  const g = ctx.createRadialGradient(VW / 2, VH * 0.42, 4, VW / 2, VH * 0.42, VW * 0.6);
  g.addColorStop(0, mix(p.bgGlow, p.bg, 0.15));
  g.addColorStop(1, p.bg);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, VW, VH);
}

function drawStarfield(
  ctx: CanvasRenderingContext2D,
  stars: Star[],
  p: Palette,
  t: number,
  reducedMotion: boolean,
) {
  for (const st of stars) {
    // Parallax drift: nearer layers slide faster. Wraps around the width.
    const speed = reducedMotion ? 0 : (st.layer + 1) * 0.004;
    const x = px(((st.x + t * speed) % VW + VW) % VW);
    const tw = reducedMotion ? 0.6 : 0.5 + 0.5 * Math.sin(t * 0.002 + st.twinkle * 6.28);
    const col = mix(p.bg, st.layer === 2 ? p.accentStrong : p.muted, 0.35 + tw * 0.5);
    ctx.fillStyle = col;
    ctx.fillRect(x, st.y, 1, 1);
    if (st.layer === 2) ctx.fillRect(x, st.y, 1, 1); // brighter near stars
  }
}

// Faint structural trusses connecting each module to the core.
function drawTrusses(ctx: CanvasRenderingContext2D, scene: SceneModel) {
  const p = scene.palette;
  ctx.strokeStyle = mix(p.border, p.bg, 0.2);
  ctx.lineWidth = 1;
  const cx = VW / 2;
  const cy = VH / 2;
  ctx.beginPath();
  for (const m of scene.modules) {
    ctx.moveTo(px(m.x + m.w / 2) + 0.5, px(m.y + m.h / 2) + 0.5);
    ctx.lineTo(px(cx) + 0.5, px(cy) + 0.5);
  }
  ctx.stroke();
}

// ── Reactor core (budget) ────────────────────────────────────────────────────
function drawReactor(ctx: CanvasRenderingContext2D, scene: SceneModel, t: number) {
  const p = scene.palette;
  const { x, y, w, h } = REACTOR;
  const powered = scene.stationPowered;

  // Housing.
  ctx.fillStyle = mix(p.panel2, p.bg, 0.1);
  ctx.fillRect(px(x), px(y), w, h);
  ctx.strokeStyle = p.border;
  ctx.lineWidth = 1;
  ctx.strokeRect(px(x) + 0.5, px(y) + 0.5, w - 1, h - 1);

  // Core fill rises with reserved+spent budget; pulses when powered.
  const fill = Math.min(1, scene.reactor.spentPct + scene.reactor.reservedPct);
  const pulse = powered ? 0.5 + 0.5 * Math.sin(t * 0.004) : 0.25;
  const coreH = Math.round((h - 8) * fill);
  const coreColor = mix(p.accent, p.accentStrong, pulse);
  ctx.fillStyle = mix(p.bg, coreColor, powered ? 0.85 : 0.35);
  ctx.fillRect(px(x) + 4, px(y + h - 4 - coreH), w - 8, coreH);

  // Spent portion sits darker at the base.
  const spentH = Math.round((h - 8) * scene.reactor.spentPct);
  ctx.fillStyle = mix(p.accent, p.bg, 0.35);
  ctx.fillRect(px(x) + 4, px(y + h - 4 - spentH), w - 8, spentH);

  // Central glow orb.
  const orbR = 5 + (powered ? Math.sin(t * 0.006) * 1.5 : 0);
  const g = ctx.createRadialGradient(x + w / 2, y + h / 2, 0, x + w / 2, y + h / 2, orbR + 4);
  g.addColorStop(0, powered ? p.accentStrong : p.muted);
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.fillRect(px(x), px(y), w, h);

  // Burn drip: little particles falling from the core when money is burning.
  if (powered && scene.reactor.burnPerDay > 0) {
    const n = 3;
    for (let i = 0; i < n; i++) {
      const phase = (t * 0.02 + i * 40) % 60;
      const dy = phase / 60;
      ctx.fillStyle = mix(p.warn, p.bg, 0.2);
      ctx.fillRect(px(x + w / 2 - 2 + i * 2), px(y + h + dy * 8), 1, 1);
    }
  }

  // Cycle progress ring around the core: a background track plus a green arc that
  // fills with the fraction of this round's tasks completed, and (while active) a
  // rotating "processing" tick so it reads as live even at 0%.
  if (scene.roundActive || scene.roundProgress > 0) {
    const cx = x + w / 2;
    const cy = y + h / 2;
    const rr = Math.max(w, h) / 2 + 5;
    const start = -Math.PI / 2; // 12 o'clock
    ctx.lineWidth = 2;
    ctx.strokeStyle = mix(p.bg, p.border, 0.9);
    ctx.beginPath();
    ctx.arc(cx, cy, rr, 0, Math.PI * 2);
    ctx.stroke();
    if (scene.roundProgress > 0) {
      ctx.strokeStyle = p.good;
      ctx.beginPath();
      ctx.arc(cx, cy, rr, start, start + scene.roundProgress * Math.PI * 2);
      ctx.stroke();
    }
    if (scene.roundActive) {
      const ang = start + (t * 0.003) % (Math.PI * 2);
      ctx.fillStyle = p.accentStrong;
      ctx.fillRect(px(cx + Math.cos(ang) * rr), px(cy + Math.sin(ang) * rr), 2, 2);
    }
  }
}

// ── Module ───────────────────────────────────────────────────────────────────
function drawModule(ctx: CanvasRenderingContext2D, m: ModuleView, p: Palette, t: number) {
  const bodyBase = m.powered ? p.panel2 : p.panel;
  const body = m.powered ? bodyBase : mix(bodyBase, p.bg, 0.4);

  // Hull.
  ctx.fillStyle = body;
  ctx.fillRect(px(m.x), px(m.y), m.w, m.h);

  // Offline hatch pattern.
  if (!m.powered) {
    ctx.fillStyle = mix(p.border, p.bg, 0.5);
    for (let yy = 0; yy < m.h; yy += 3) {
      for (let xx = (yy % 6 === 0 ? 0 : 2); xx < m.w; xx += 4) {
        ctx.fillRect(px(m.x + xx), px(m.y + yy), 1, 1);
      }
    }
  }

  // Border — accent when powered, danger flash when alerting.
  let border = m.powered ? p.accent : p.border;
  if (m.alert) {
    const flash = 0.5 + 0.5 * Math.sin(t * 0.01);
    border = mix(p.danger, p.warn, flash);
  }
  ctx.strokeStyle = border;
  ctx.lineWidth = 1;
  ctx.strokeRect(px(m.x) + 0.5, px(m.y) + 0.5, m.w - 1, m.h - 1);

  // Lit windows along the top when powered.
  const winColor = m.powered ? mix(p.accentStrong, p.panel, 0.15) : mix(p.muted, p.bg, 0.5);
  const winY = m.y + 4;
  for (let wx = m.x + 4; wx < m.x + m.w - 3; wx += 5) {
    const on = m.powered ? (Math.sin(t * 0.003 + wx) > -0.6 ? 1 : 0.4) : 1;
    ctx.fillStyle = m.powered ? mix(p.panel, winColor, on) : winColor;
    ctx.fillRect(px(wx), px(winY), 2, 2);
  }

  // Working scan: an indeterminate highlight sweeping across the hull + a
  // pulsing worklight dot, so a module with a running task reads as busy.
  if (m.working) {
    const inner = m.w - 4;
    const sweepW = 8;
    const pos = ((t * 0.04) % (inner + sweepW)) - sweepW; // slides L→R and wraps
    for (let i = 0; i < sweepW; i++) {
      const sx = m.x + 2 + pos + i;
      if (sx < m.x + 2 || sx > m.x + m.w - 2) continue;
      const a = 1 - Math.abs(i - sweepW / 2) / (sweepW / 2);
      ctx.fillStyle = mix(body, p.accentStrong, a * 0.7);
      ctx.fillRect(px(sx), px(m.y + m.h - 7), 1, 3);
    }
    // Blinking worklight (top-left).
    if (Math.sin(t * 0.02) > 0) {
      ctx.fillStyle = p.good;
      ctx.fillRect(px(m.x + 2), px(m.y + 2), 2, 2);
    }
  }

  // Short role tag (tiny pixel label bar) along the bottom edge.
  ctx.fillStyle = m.powered ? mix(p.accent, p.panel2, 0.4) : mix(p.border, p.bg, 0.3);
  ctx.fillRect(px(m.x + 2), px(m.y + m.h - 4), Math.min(m.w - 4, m.short.length * 3 + 2), 2);

  // Alert badge (top-right corner).
  if (m.alert) {
    const flash = 0.5 + 0.5 * Math.sin(t * 0.01);
    ctx.fillStyle = mix(p.danger, p.warn, flash);
    ctx.fillRect(px(m.x + m.w - 5), px(m.y + 1), 3, 3);
  }
}

// ── Droid sprite ─────────────────────────────────────────────────────────────
// 7×7 crew droid. Chars: '.' transparent, 'b' body, 'h' head/glass, 'e' eye,
// 'f' foot/shadow. Colours resolved per-palette below.
const DROID_SPRITE = [
  "..hhh..",
  ".hhehh.",
  ".hhhhh.",
  "bbbbbbb",
  "b.bbb.b",
  ".bbbbb.",
  ".f...f.",
];

function drawDroid(ctx: CanvasRenderingContext2D, d: { x: number; y: number; powered: boolean; rankStars: number; bobSeed: number }, p: Palette, t: number) {
  const bob = d.powered ? Math.round(Math.sin(t * 0.004 + d.bobSeed * 6.28)) : 0;
  const ox = px(d.x - 3);
  const oy = px(d.y - 6 + bob);

  const body = d.powered ? p.accent : mix(p.muted, p.bg, 0.4);
  const glass = d.powered ? p.accentStrong : mix(p.muted, p.bg, 0.3);
  const eye = d.powered ? p.onAccent : p.muted;
  const foot = mix(p.bg, p.border, 0.6);

  for (let row = 0; row < DROID_SPRITE.length; row++) {
    const line = DROID_SPRITE[row];
    for (let col = 0; col < line.length; col++) {
      const c = line[col];
      if (c === ".") continue;
      ctx.fillStyle = c === "b" ? body : c === "h" ? glass : c === "e" ? eye : foot;
      ctx.fillRect(ox + col, oy + row, 1, 1);
    }
  }

  // Rank stars as pips above the droid.
  if (d.rankStars > 0) {
    for (let i = 0; i < d.rankStars; i++) {
      ctx.fillStyle = p.warn;
      ctx.fillRect(ox + i * 2, oy - 3, 1, 1);
    }
  }
}

// ── Mission orbs (tasks) ─────────────────────────────────────────────────────
function orbColor(status: MissionOrb["status"], p: Palette): string {
  switch (status) {
    case "running":
      return p.accent;
    case "queued":
      return p.muted;
    case "done":
      return p.good;
    case "failed":
      return p.danger;
    case "waiting_approval":
      return p.warn;
  }
}

function drawMissionOrb(
  ctx: CanvasRenderingContext2D,
  orb: MissionOrb,
  scene: SceneModel,
  p: Palette,
  t: number,
) {
  const from = orb.fromKey ? scene.modules.find((m) => m.key === orb.fromKey) : undefined;
  const sx = from ? from.x + from.w / 2 : VW / 2;
  const sy = from ? from.y + from.h / 2 : VH / 2;
  const cx = VW / 2;
  const cy = VH / 2;

  // Travel parameter oscillates module→core→module so orbs shuttle work in.
  const speed = orb.status === "running" ? 0.0009 : 0.0004;
  const tri = (Math.sin(t * speed + orb.seed * 6.28) + 1) / 2; // 0..1
  const x = px(sx + (cx - sx) * tri);
  const y = px(sy + (cy - sy) * tri);

  const col = orbColor(orb.status, p);
  const pulse = 0.6 + 0.4 * Math.sin(t * 0.008 + orb.seed * 6.28);
  ctx.fillStyle = orb.status === "running" ? mix(p.bg, col, pulse) : col;
  ctx.fillRect(x, y, 2, 2);
  // Trailing pixel for a sense of motion.
  ctx.fillStyle = mix(p.bg, col, 0.4);
  ctx.fillRect(px(x - Math.sign(cx - sx)), y, 1, 1);
}

// ── Planets (sites / leads) ──────────────────────────────────────────────────
function drawPlanets(ctx: CanvasRenderingContext2D, planets: PlanetView[], p: Palette, t: number) {
  for (const pl of planets) {
    const cx = px(pl.x);
    const cy = px(pl.y);
    const base = pl.lit ? p.good : p.muted;
    // Simple filled disc via a few rects (pixel circle).
    for (let dy = -pl.r; dy <= pl.r; dy++) {
      const span = Math.floor(Math.sqrt(pl.r * pl.r - dy * dy));
      ctx.fillStyle = mix(p.bg, base, dy < 0 ? 0.9 : 0.6); // light from top
      ctx.fillRect(cx - span, cy + dy, span * 2 + 1, 1);
    }
    // Docked-ship pips = leads orbiting the planet.
    const ships = Math.min(4, pl.leads);
    for (let i = 0; i < ships; i++) {
      const ang = t * 0.001 + (i / Math.max(1, ships)) * Math.PI * 2 + pl.seed * 6.28;
      const ox = px(pl.x + Math.cos(ang) * (pl.r + 3));
      const oy = px(pl.y + Math.sin(ang) * (pl.r + 2));
      ctx.fillStyle = p.accentStrong;
      ctx.fillRect(ox, oy, 1, 1);
    }
  }
}

// ── Powering-up overlay (draft / not-active company) ─────────────────────────
function drawPoweringUp(ctx: CanvasRenderingContext2D, scene: SceneModel, p: Palette, t: number) {
  // Dim the whole scene and pulse a "POWERING UP" bar.
  ctx.fillStyle = "rgba(4,8,16,0.45)";
  ctx.fillRect(0, 0, VW, VH);

  const blink = 0.5 + 0.5 * Math.sin(t * 0.005);
  const barW = 120;
  const barX = px(VW / 2 - barW / 2);
  const barY = px(VH - 30);
  ctx.strokeStyle = mix(p.border, p.accent, blink);
  ctx.lineWidth = 1;
  ctx.strokeRect(barX + 0.5, barY + 0.5, barW - 1, 6);
  // Marching fill.
  const fillW = px(((t * 0.03) % barW));
  ctx.fillStyle = mix(p.accent, p.accentStrong, blink);
  ctx.fillRect(barX + 2, barY + 2, Math.max(2, Math.min(barW - 4, fillW)), 2);
}

// ── Transient FX (drives round playback, score pops, level-ups) ───────────────
// A tiny 3×5 pixel font — digits + and −, enough for floating "+N" score pops.
const GLYPHS: Record<string, string[]> = {
  "0": ["111", "101", "101", "101", "111"],
  "1": ["010", "110", "010", "010", "111"],
  "2": ["111", "001", "111", "100", "111"],
  "3": ["111", "001", "111", "001", "111"],
  "4": ["101", "101", "111", "001", "001"],
  "5": ["111", "100", "111", "001", "111"],
  "6": ["111", "100", "111", "101", "111"],
  "7": ["111", "001", "010", "010", "010"],
  "8": ["111", "101", "111", "101", "111"],
  "9": ["111", "101", "111", "001", "111"],
  "+": ["000", "010", "111", "010", "000"],
  "-": ["000", "000", "111", "000", "000"],
};

function drawGlyphs(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, color: string) {
  ctx.fillStyle = color;
  let ox = px(x);
  for (const ch of text) {
    const g = GLYPHS[ch];
    if (g) {
      for (let row = 0; row < 5; row++) {
        for (let col = 0; col < 3; col++) {
          if (g[row][col] === "1") ctx.fillRect(ox + col, px(y) + row, 1, 1);
        }
      }
    }
    ox += 4; // 3px glyph + 1px space
  }
}

// Draw the FX queue, expire dead events (single owner of expiry), and accumulate
// a screen-shake offset the loop applies to the blit.
function drawFx(
  ctx: CanvasRenderingContext2D,
  fx: FxQueue,
  p: Palette,
  nowMs: number,
  reducedMotion: boolean,
): { shakeX: number; shakeY: number } {
  let shakeX = 0;
  let shakeY = 0;
  const alive: FxEvent[] = [];

  for (const e of fx.events) {
    const age = nowMs - e.bornMs;
    if (age > e.ttlMs) continue; // expired — drop
    alive.push(e);
    // Clamp progress: born/now come from slightly different performance.now()
    // reads (differ vs rAF), so age can be a hair negative on the first frame.
    const k = Math.max(0, Math.min(1, age / e.ttlMs)); // 0..1 progress
    const d = e.data;
    const num = (key: string) => (typeof d[key] === "number" ? (d[key] as number) : 0);

    switch (e.kind) {
      case "taskBurst": {
        const col = d.good ? p.good : p.danger;
        const r = 1 + k * 7;
        const a = 1 - k;
        ctx.fillStyle = mix(p.bg, col, a);
        // ring of 8 pixels expanding outward
        for (let i = 0; i < 8; i++) {
          const ang = (i / 8) * Math.PI * 2;
          ctx.fillRect(px(num("x") + Math.cos(ang) * r), px(num("y") + Math.sin(ang) * r), 1, 1);
        }
        break;
      }
      case "orbLaunch": {
        const rise = reducedMotion ? 0 : k * 8;
        ctx.fillStyle = mix(p.bg, p.accentStrong, 1 - k);
        ctx.fillRect(px(num("x")), px(num("y") - rise), 1, 2);
        break;
      }
      case "leadLand": {
        const fall = reducedMotion ? 6 : k * 8;
        ctx.fillStyle = mix(p.bg, p.good, 1 - Math.abs(k - 0.5) * 2);
        ctx.fillRect(px(num("x")), px(num("y") - 8 + fall), 1, 2);
        break;
      }
      case "scorePop": {
        const rise = reducedMotion ? 0 : k * 12;
        const col = d.good === false ? p.danger : p.accentStrong;
        const val = num("value");
        const text = `${val >= 0 ? "+" : "-"}${Math.abs(val)}`;
        drawGlyphs(ctx, text, num("x"), num("y") - rise, mix(p.bg, col, Math.max(0.2, 1 - k)));
        break;
      }
      case "rankUp": {
        const rise = reducedMotion ? 3 : k * 6;
        ctx.fillStyle = mix(p.bg, p.warn, 1 - k);
        for (let i = -1; i <= 1; i++) ctx.fillRect(px(num("x") + i * 2), px(num("y") - 4 - rise), 1, 1);
        break;
      }
      case "cycleStart": {
        // A light sweep ring expanding from the CEO module along the hull.
        const r = k * VW * 0.5;
        ctx.strokeStyle = mix(p.bg, p.accent, 1 - k);
        ctx.beginPath();
        ctx.arc(num("x"), num("y"), r, 0, Math.PI * 2);
        ctx.stroke();
        break;
      }
      case "levelUp": {
        // Full-width banner sweep + upward chevrons + a brief palette flash.
        const flash = k < 0.15 ? (0.15 - k) / 0.15 : 0;
        if (flash > 0) {
          ctx.fillStyle = mix(p.bg, p.accentStrong, flash * 0.5);
          ctx.fillRect(0, 0, VW, VH);
        }
        const by = px(VH * 0.5 - 8);
        ctx.fillStyle = mix(p.bg, p.accent, 0.6 * (1 - k));
        ctx.fillRect(0, by, VW, 16);
        ctx.fillStyle = mix(p.bg, p.accentStrong, 1 - k);
        const sweep = reducedMotion ? VW / 2 : (k * VW * 1.4) % VW;
        for (let i = 0; i < 3; i++) {
          const cx = px(sweep - i * 6);
          ctx.fillRect(cx, by + 8, 1, -4); // up-chevron stem
          ctx.fillRect(cx - 1, by + 6, 1, 1);
          ctx.fillRect(cx + 1, by + 6, 1, 1);
        }
        break;
      }
      case "shake": {
        const mag = num("mag") * (1 - k);
        // Deterministic wobble from the event id + time so it's stable per-frame.
        shakeX += Math.round(Math.sin(nowMs * 0.05 + e.id) * mag);
        shakeY += Math.round(Math.cos(nowMs * 0.07 + e.id) * mag);
        break;
      }
    }
  }

  fx.events = alive;
  return { shakeX, shakeY };
}
