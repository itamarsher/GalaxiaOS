"use client";

// Galaxia Command — operate your autonomous company as a pixel-art starbase.
//
// This page orchestrates: it polls the live company data, folds it into a
// SceneModel (lib/game/scene.ts), hands that to the rAF loop (useStationLoop)
// via a ref, and lays out the animated canvas beside the DOM HUD (hud.tsx).
// The canvas is decorative; every action also exists as a real DOM control.

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { usePoll, useLiveTasks } from "@/lib/useApi";
import { buildScene, VH, VW, type ModuleView, type SceneModel } from "@/lib/game/scene";
import { useStationLoop, type HitLayout } from "@/lib/game/useStationLoop";
import {
  CaptainsConsole,
  CrewRoster,
  Legend,
  ModuleSheet,
  ModuleTooltip,
  ReactorGauge,
  RunwayGauge,
  ScorePanel,
} from "./hud";

export default function GalaxiaCommandPage() {
  const { id } = useParams<{ id: string }>();

  // ── Live data (HUD state; also copied into sceneRef for the loop) ──────────
  const company = usePoll(() => api.company(id), 10000, [id]);
  const org = usePoll(() => api.org(id), 5000, [id]);
  const budget = usePoll(() => api.budget(id), 5000, [id]);
  const runway = usePoll(() => api.runway(id), 15000, [id]);
  const decisions = usePoll(() => api.decisions(id, true), 5000, [id]);
  const reputation = usePoll(() => api.reputation(id), 15000, [id]);
  const sites = usePoll(() => api.sites(id), 15000, [id]);
  const tasks = useLiveTasks(id);

  const agents = useMemo(() => org.data?.agents ?? [], [org.data]);

  // ── Scene model → ref (loop reads only the ref, never React state) ─────────
  const scene: SceneModel = useMemo(
    () =>
      buildScene({
        companyStatus: company.data?.status ?? null,
        agents,
        tasks,
        budget: budget.data,
        runway: runway.data,
        reputation: reputation.data ?? [],
        sites: sites.data ?? [],
      }),
    [company.data?.status, agents, tasks, budget.data, runway.data, reputation.data, sites.data],
  );

  const sceneRef = useRef<SceneModel | null>(null);
  useEffect(() => {
    sceneRef.current = scene;
  }, [scene]);

  // ── Canvas + loop ──────────────────────────────────────────────────────────
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const hitRef = useRef<HitLayout | null>(null);
  useStationLoop({ canvasRef, sceneRef, hitRef });

  // ── Pointer interaction ────────────────────────────────────────────────────
  const coarse =
    typeof window !== "undefined" && window.matchMedia?.("(hover: none)").matches;
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [sheetModule, setSheetModule] = useState<ModuleView | null>(null);
  const [hover, setHover] = useState<{ module: ModuleView; left: number; top: number } | null>(null);
  const moveThrottle = useRef(0);

  // Convert a client point to a module under the pointer using the shared hit layout.
  const moduleAt = (clientX: number, clientY: number): ModuleView | null => {
    const el = canvasRef.current;
    const layout = hitRef.current;
    if (!el || !layout) return null;
    const rect = el.getBoundingClientRect();
    const vx = ((clientX - rect.left) * layout.dpr - layout.offsetX) / layout.scale;
    const vy = ((clientY - rect.top) * layout.dpr - layout.offsetY) / layout.scale;
    if (vx < 0 || vy < 0 || vx > VW || vy > VH) return null;
    const hit = layout.modules.find(
      (m) => vx >= m.x && vx <= m.x + m.w && vy >= m.y && vy <= m.y + m.h,
    );
    if (!hit) return null;
    return scene.modules.find((m) => m.key === hit.key) ?? null;
  };

  const toggleAgent = async (m: ModuleView) => {
    if (!m.agentId || busyKey) return;
    setBusyKey(m.key);
    try {
      if (m.status === "paused") await api.resumeAgent(id, m.agentId);
      else await api.pauseAgent(id, m.agentId);
      await org.reload();
    } finally {
      setBusyKey(null);
      setSheetModule(null);
    }
  };

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const m = moduleAt(e.clientX, e.clientY);
    if (!m || !m.agentId) return;
    if (coarse) {
      setSheetModule(m); // touch: open the action sheet
    } else {
      void toggleAgent(m); // mouse: direct toggle
    }
  };

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (coarse) return; // no hover on touch
    const now = e.timeStamp;
    if (now - moveThrottle.current < 40) return;
    moveThrottle.current = now;
    const el = canvasRef.current;
    const m = moduleAt(e.clientX, e.clientY);
    if (m && el) {
      const rect = el.getBoundingClientRect();
      const layout = hitRef.current;
      const scale = layout ? layout.scale / layout.dpr : 1;
      setHover({
        module: m,
        left: rect.left + (m.x + m.w / 2) * scale - (layout?.offsetX ?? 0) / (layout?.dpr ?? 1),
        top: rect.top + (m.y + m.h) * scale + 6 - (layout?.offsetY ?? 0) / (layout?.dpr ?? 1),
      });
      el.style.cursor = "pointer";
    } else {
      if (hover) setHover(null);
      if (el) el.style.cursor = "default";
    }
  };

  const decisionList = decisions.data ?? [];

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>
          Galaxia Command <span className="muted" style={{ fontSize: 14 }}>· {company.data?.name ?? "Starbase"}</span>
        </h2>
        <span className={`status ${company.data?.status ?? ""}`}>{company.data?.status ?? "—"}</span>
      </div>
      <p className="muted" style={{ marginTop: 4 }}>
        Your company as a living starbase. Crew droids man the modules, the reactor is your budget,
        life support is your runway — and the Captain&apos;s Console is where you give the orders.
      </p>

      <div className="gamewrap">
        {/* The animated station scene. Decorative — actions mirror in the DOM below. */}
        <div className="station-stage">
          <canvas
            ref={canvasRef}
            className="station-canvas"
            role="img"
            aria-label={`Pixel-art starbase for ${company.data?.name ?? "your company"}, command rating ${scene.health} of 100`}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerLeave={() => setHover(null)}
          />
          {hover && <ModuleTooltip module={hover.module} left={hover.left} top={hover.top} />}
        </div>

        {/* HUD. Order matters on mobile (single column): console first. */}
        <div className="hud-grid">
          <div className="hud-primary">
            <CaptainsConsole companyId={id} decisions={decisionList} onResolved={() => decisions.reload()} />
          </div>
          <div className="hud-gauges">
            <ScorePanel health={scene.health} />
            <RunwayGauge runway={runway.data} />
            <ReactorGauge budget={budget.data} />
          </div>
          <div className="hud-secondary">
            <CrewRoster modules={scene.modules} onToggle={toggleAgent} busyKey={busyKey} />
            <Legend />
          </div>
        </div>
      </div>

      {sheetModule && (
        <ModuleSheet
          module={sheetModule}
          busy={busyKey === sheetModule.key}
          onToggle={toggleAgent}
          onClose={() => setSheetModule(null)}
        />
      )}
    </div>
  );
}
