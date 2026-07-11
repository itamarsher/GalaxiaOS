"use client";

// Galaxia Command — operate your autonomous company as a pixel-art starbase GAME.
//
// The core loop is the real business cycle: "Advance cycle" triggers one
// (POST /cycle), and the round plays out live over the SSE task stream. The page
// polls live data, folds it into a SceneModel + RoundState, drives transient
// canvas FX from data deltas (via a ref-owned queue the rAF loop consumes), and
// lays out the DOM HUD (swipe-to-decide console, level/XP meter, gauges). Every
// gesture also has an accessible DOM control.

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { usePoll, useLiveCompanyFeed } from "@/lib/useApi";
import {
  buildScene,
  moduleAnchor,
  sectorStanding,
  REACTOR,
  VH,
  VW,
  type ModuleView,
  type SceneModel,
} from "@/lib/game/scene";
import { buildQuests } from "@/lib/game/quests";
import { useStationLoop, type HitLayout } from "@/lib/game/useStationLoop";
import { makeFxQueue, FX_TTL, type FxQueue } from "@/lib/game/fx";
import { deriveRound, phaseLabel, type RoundState } from "@/lib/game/round";
import {
  comboMultiplier,
  isGoodRound,
  loadProgress,
  roundScore,
  saveProgress,
  totalLeads,
  totalScore,
} from "@/lib/game/score";
import { AdvanceButton } from "./AdvanceButton";
import {
  CaptainsConsole,
  CrewRoster,
  CycleProgress,
  Legend,
  MissionLog,
  ModuleSheet,
  ModuleTooltip,
  QuestLog,
  ReactorGauge,
  RunwayGauge,
  ScorePanel,
} from "./hud";

const STANDINGS = ["Outpost", "Station", "Starbase", "Citadel"];

export default function GalaxiaCommandPage() {
  const { id } = useParams<{ id: string }>();

  // ── Live data ──────────────────────────────────────────────────────────────
  const company = usePoll(() => api.company(id), 10000, [id]);
  const org = usePoll(() => api.org(id), 5000, [id]);
  const budget = usePoll(() => api.budget(id), 5000, [id]);
  const runway = usePoll(() => api.runway(id), 15000, [id]);
  const decisions = usePoll(() => api.decisions(id, true), 5000, [id]);
  const reputation = usePoll(() => api.reputation(id), 15000, [id]);
  const sites = usePoll(() => api.sites(id), 15000, [id]);
  const cycle = usePoll(() => api.cycleStatus(id), 8000, [id]);
  const objectives = usePoll(() => api.objectives(id), 15000, [id]);
  const chatChannels = usePoll(() => api.chatChannels(id), 5000, [id]);
  const { tasks, missionLog } = useLiveCompanyFeed(id);

  const agents = useMemo(() => org.data?.agents ?? [], [org.data]);

  // Business objectives → live quest board, progress derived from this cycle's tasks.
  const quests = useMemo(
    () => buildQuests(objectives.data ?? [], tasks),
    [objectives.data, tasks],
  );

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

  const round: RoundState = useMemo(() => deriveRound(tasks), [tasks]);

  // ── Score / streak (derived + persisted) ───────────────────────────────────
  const doneCount = useMemo(() => tasks.filter((t) => t.status === "done").length, [tasks]);
  const leads = useMemo(() => totalLeads(sites.data ?? []), [sites.data]);
  const score = useMemo(
    () => totalScore(scene.health, doneCount, leads, reputation.data ?? []),
    [scene.health, doneCount, leads, reputation.data],
  );
  const [streak, setStreak] = useState(0);
  useEffect(() => {
    setStreak(loadProgress(id).streak);
  }, [id]);

  // ── Canvas + FX loop ─────────────────────────────────────────────────────────
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const hitRef = useRef<HitLayout | null>(null);
  const sceneRef = useRef<SceneModel | null>(null);
  const fxRef = useRef<FxQueue | null>(null);
  if (fxRef.current === null) fxRef.current = makeFxQueue();
  useEffect(() => {
    sceneRef.current = scene;
  }, [scene]);
  useStationLoop({ canvasRef, sceneRef, hitRef, fxRef });

  // ── Data-delta differ → FX + streak + announcements (never per-frame) ────────
  const mounted = useRef(false);
  const prevTaskStatus = useRef<Map<string, string>>(new Map());
  const prevLeads = useRef<Map<string, number>>(new Map());
  const prevRank = useRef<Map<string, number>>(new Map());
  const prevStanding = useRef<string>("Outpost");
  const prevPhase = useRef<string>("idle");
  const prevRootKey = useRef<string | null>(null);
  const [announce, setAnnounce] = useState("");

  // Quest transitions: ids that just appeared / just cleared drive one-shot CSS
  // flourishes in the QuestLog. They live in state briefly, then self-expire.
  const [newQuestIds, setNewQuestIds] = useState<Set<string>>(new Set());
  const [clearedQuestIds, setClearedQuestIds] = useState<Set<string>>(new Set());
  const questMounted = useRef(false);
  const prevQuestStatus = useRef<Map<string, string>>(new Map());
  const expireIds = (setter: typeof setNewQuestIds, ids: string[], ms: number) => {
    setter((prev) => new Set([...prev, ...ids]));
    setTimeout(() => {
      setter((prev) => {
        const next = new Set(prev);
        for (const idv of ids) next.delete(idv);
        return next;
      });
    }, ms);
  };

  useEffect(() => {
    const fx = fxRef.current;
    if (!fx) return;
    const now = typeof performance !== "undefined" ? performance.now() : 0;
    const anchorOf = (key: string | null) => moduleAnchor(scene, key);

    // First run: seed prev snapshots without emitting a flood of FX.
    if (!mounted.current) {
      for (const t of tasks) prevTaskStatus.current.set(t.id, t.status);
      for (const pl of scene.planets) prevLeads.current.set(pl.id, pl.leads);
      for (const m of scene.modules) prevRank.current.set(m.key, m.rankStars);
      prevStanding.current = sectorStanding(scene.health);
      prevPhase.current = round.phase;
      prevRootKey.current = round.rootKey;
      mounted.current = true;
      return;
    }

    // Task status transitions → bursts / orb launches.
    const seen = new Set<string>();
    for (const t of tasks) {
      seen.add(t.id);
      const prev = prevTaskStatus.current.get(t.id);
      if (prev !== t.status) {
        const a = anchorOf(t.agent_id);
        if (t.status === "done" || t.status === "failed") {
          const good = t.status === "done";
          fx.push("taskBurst", FX_TTL.taskBurst, { x: a.x, y: a.y, good }, now);
          const mult = comboMultiplier(streak);
          fx.push(
            "scorePop",
            FX_TTL.scorePop,
            { x: a.x, y: a.y - 4, value: Math.round((good ? 10 : -6) * mult), good },
            now,
          );
        } else if (prev === undefined || prev === "queued" || t.status === "running") {
          fx.push("orbLaunch", FX_TTL.orbLaunch, { x: a.x, y: a.y }, now);
        }
        prevTaskStatus.current.set(t.id, t.status);
      }
    }
    for (const id2 of [...prevTaskStatus.current.keys()]) if (!seen.has(id2)) prevTaskStatus.current.delete(id2);

    // Lead landings.
    for (const pl of scene.planets) {
      const prev = prevLeads.current.get(pl.id) ?? 0;
      if (pl.leads > prev) fx.push("leadLand", FX_TTL.leadLand, { x: pl.x, y: pl.y }, now);
      prevLeads.current.set(pl.id, pl.leads);
    }

    // Rank ups.
    for (const m of scene.modules) {
      const prev = prevRank.current.get(m.key) ?? 0;
      if (m.rankStars > prev) {
        const a = anchorOf(m.key);
        fx.push("rankUp", FX_TTL.rankUp, { x: a.x, y: a.y }, now);
      }
      prevRank.current.set(m.key, m.rankStars);
    }

    // Level up (sector standing rose a band).
    const standing = sectorStanding(scene.health);
    if (STANDINGS.indexOf(standing) > STANDINGS.indexOf(prevStanding.current)) {
      fx.push("levelUp", FX_TTL.levelUp, { label: standing }, now);
      fx.push("shake", FX_TTL.shake, { mag: 3 }, now);
      fx.push("scorePop", FX_TTL.scorePop, { x: VW / 2, y: VH / 2 - 12, value: 100, good: true }, now);
      setAnnounce(`Level up! Now a ${standing}.`);
    }
    prevStanding.current = standing;

    // New round began.
    if (round.rootKey && round.rootKey !== prevRootKey.current) {
      const a = anchorOf("ceo");
      fx.push("cycleStart", FX_TTL.cycleStart, { x: a.x, y: a.y }, now);
    }
    prevRootKey.current = round.rootKey;

    // Round settled → streak + outcome announcement (edge-triggered, once).
    if (round.phase === "settled" && prevPhase.current !== "settled") {
      const good = isGoodRound(round.counts);
      setStreak((s) => {
        const ns = good ? s + 1 : 0;
        const prog = loadProgress(id);
        saveProgress(id, { ...prog, streak: ns, bestScore: Math.max(prog.bestScore, score) });
        return ns;
      });
      const rs = roundScore(round.counts, 0, 0);
      fx.push(
        "scorePop",
        FX_TTL.scorePop,
        { x: VW / 2, y: VH / 2 + 8, value: rs, good: rs >= 0 },
        now,
      );
      setAnnounce(`Cycle complete: ${round.counts.done} done, ${round.counts.failed} failed.`);
      if (!good && round.counts.failed > 0) fx.push("shake", FX_TTL.shake, { mag: 2 }, now);
    } else if (round.phase !== prevPhase.current && round.phase !== "settled") {
      setAnnounce(phaseLabel(round.phase));
    }
    prevPhase.current = round.phase;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks, scene, round, id]);

  // ── Quest differ → new/cleared flourishes + canvas celebration FX ────────────
  useEffect(() => {
    const fx = fxRef.current;
    const now = typeof performance !== "undefined" ? performance.now() : 0;
    const core = { x: REACTOR.x + REACTOR.w / 2, y: REACTOR.y + REACTOR.h / 2 };

    // First run: seed statuses without firing a flood of "new quest" FX.
    if (!questMounted.current) {
      for (const q of quests) prevQuestStatus.current.set(q.id, q.status);
      questMounted.current = true;
      return;
    }

    const appeared: string[] = [];
    const cleared: string[] = [];
    const seen = new Set<string>();
    for (const q of quests) {
      seen.add(q.id);
      const prev = prevQuestStatus.current.get(q.id);
      if (prev === undefined) appeared.push(q.id);
      else if (prev !== "complete" && q.status === "complete") cleared.push(q.id);
      prevQuestStatus.current.set(q.id, q.status);
    }
    for (const k of [...prevQuestStatus.current.keys()]) {
      if (!seen.has(k)) prevQuestStatus.current.delete(k);
    }

    if (appeared.length > 0) {
      if (fx) fx.push("questNew", FX_TTL.questNew, { x: core.x, y: core.y }, now);
      expireIds(setNewQuestIds, appeared, 1400);
      const first = quests.find((q) => q.id === appeared[0]);
      setAnnounce(
        appeared.length > 1
          ? `${appeared.length} new quests posted.`
          : `New quest posted: ${first?.title ?? ""}.`,
      );
    }
    if (cleared.length > 0) {
      if (fx) {
        fx.push("questDone", FX_TTL.questDone, { x: core.x, y: core.y }, now);
        fx.push("scorePop", FX_TTL.scorePop, { x: core.x, y: core.y - 14, value: 25, good: true }, now);
        fx.push("shake", FX_TTL.shake, { mag: 2 }, now);
      }
      expireIds(setClearedQuestIds, cleared, 1800);
      const first = quests.find((q) => q.id === cleared[0]);
      setAnnounce(`Quest cleared: ${first?.title ?? ""}.`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quests]);

  // ── Pointer interaction (module pause/resume) ────────────────────────────────
  const coarse =
    typeof window !== "undefined" && window.matchMedia?.("(hover: none)").matches;
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [sheetModule, setSheetModule] = useState<ModuleView | null>(null);
  const [hover, setHover] = useState<{ module: ModuleView; left: number; top: number } | null>(null);
  const moveThrottle = useRef(0);

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
    if (coarse) setSheetModule(m);
    else void toggleAgent(m);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (coarse) return;
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
  const cycleData = cycle.data;
  // Agents can also park a task waiting for a plain chat reply (no formal
  // decision) — that still counts as "awaiting you" in the cycle strip, so the
  // console must point the founder to Chat rather than claiming "all clear".
  // Consider only pure chat-waits (a channel whose pending_decision is already in
  // the decision deck isn't double-counted here).
  const waitingChannels = (chatChannels.data ?? []).filter(
    (c) => c.pending_decision == null && c.waiting_agents.length > 0,
  );
  const chatWaiting = waitingChannels.reduce((n, c) => n + c.waiting_agents.length, 0);
  // Formatted "Name (role)" labels so the console can name a lone waiting agent.
  const chatWaitingAgents = waitingChannels.flatMap((c) => c.waiting_agents);
  // Deep-link straight to the waiting conversation (?channel=…); the chat page's
  // own default would otherwise open the CEO DM, not where the reply is owed.
  const chatHref =
    waitingChannels.length > 0
      ? `/c/${id}/chat?channel=${waitingChannels[0].id}`
      : `/c/${id}/chat`;

  return (
    <div>
      <div className="game-header">
        <h2 style={{ margin: 0 }}>
          Galaxia Command <span className="muted" style={{ fontSize: 14 }}>· {company.data?.name ?? "Starbase"}</span>
        </h2>
        <AdvanceButton
          companyId={id}
          phase={round.phase}
          canStart={cycleData?.can_start ?? false}
          statusReason={cycleData?.reason ?? "already_running"}
          onAdvanced={() => { cycle.reload(); }}
        />
      </div>
      <p className="muted" style={{ marginTop: 4 }}>
        Advance a cycle to run your fleet. Watch the round play out, swipe to give orders, and level
        up your starbase.
      </p>

      {/* Screen-reader announcer for canvas-only FX and round phases. */}
      <div aria-live="polite" className="sr-only">{announce}</div>

      {/* Live cycle/task progress while a round runs. */}
      <CycleProgress round={round} />

      <div className="gamewrap">
        <div className="station-stage">
          <canvas
            ref={canvasRef}
            className="station-canvas"
            role="img"
            aria-label={`Pixel-art starbase for ${company.data?.name ?? "your company"} — ${phaseLabel(round.phase)}, command rating ${scene.health} of 100`}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerLeave={() => setHover(null)}
          />
          {hover && <ModuleTooltip module={hover.module} left={hover.left} top={hover.top} />}
        </div>

        <QuestLog quests={quests} newIds={newQuestIds} clearedIds={clearedQuestIds} />

        <MissionLog entries={missionLog} />

        <div className="hud-grid">
          <div className="hud-primary">
            <CaptainsConsole
              decisions={decisionList}
              chatWaiting={chatWaiting}
              chatWaitingAgents={chatWaitingAgents}
              chatHref={chatHref}
              onResolved={() => decisions.reload()}
            />
          </div>
          <div className="hud-gauges">
            <ScorePanel health={scene.health} score={score} streak={streak} />
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
