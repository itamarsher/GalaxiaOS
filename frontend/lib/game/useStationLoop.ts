"use client";

// Galaxia Command — the requestAnimationFrame loop.
//
// Owns everything that must NOT trigger React renders: an offscreen low-res
// buffer, DPR/resize handling, the integer upscale + letterbox transform, the
// visibility pause, and publishing the current transform into `hitRef` so the
// page's pointer hit-testing and the renderer share one source of truth.
//
// The loop reads scene data from `sceneRef` only — data polling lives in the
// page and writes the latest SceneModel into that ref, so poll-driven React
// re-renders never reset the animation (which is time-based via performance.now).

import { useEffect, type RefObject } from "react";
import { makeStarfield, renderStation, type Star } from "./render";
import { hitModules, VH, VW, type HitModule, type SceneModel } from "./scene";

export interface HitLayout {
  scale: number; // integer upscale factor S
  offsetX: number; // letterbox offset in backing-store px
  offsetY: number;
  dpr: number;
  modules: HitModule[];
}

interface Options {
  canvasRef: RefObject<HTMLCanvasElement | null>;
  sceneRef: RefObject<SceneModel | null>;
  hitRef: RefObject<HitLayout | null>;
}

export function useStationLoop({ canvasRef, sceneRef, hitRef }: Options): void {
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Offscreen buffer we draw the scene into at native virtual resolution.
    const buffer = document.createElement("canvas");
    buffer.width = VW;
    buffer.height = VH;
    const bctx = buffer.getContext("2d");
    if (!bctx) return;
    bctx.imageSmoothingEnabled = false;

    const stars: Star[] = makeStarfield(90);
    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

    let raf = 0;
    let lastFrame = 0;

    // Recompute backing-store size + integer scale. Called on mount and resize.
    function resize() {
      const el = canvasRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const backingW = Math.max(1, Math.round(rect.width * dpr));
      const backingH = Math.max(1, Math.round(rect.height * dpr));
      if (el.width !== backingW) el.width = backingW;
      if (el.height !== backingH) el.height = backingH;
      const scale = Math.max(1, Math.floor(Math.min(backingW / VW, backingH / VH)));
      const offsetX = Math.floor((backingW - VW * scale) / 2);
      const offsetY = Math.floor((backingH - VH * scale) / 2);
      hitRef.current = { scale, offsetX, offsetY, dpr, modules: hitRef.current?.modules ?? [] };
    }

    function frame(now: number) {
      raf = requestAnimationFrame(frame);
      // Pause work entirely when the tab is hidden.
      if (document.hidden) return;
      // Soft 30fps cap — plenty for pixel motion, easy on phone batteries.
      if (now - lastFrame < 33) return;
      lastFrame = now;

      const scene = sceneRef.current;
      const el = canvasRef.current;
      const layout = hitRef.current;
      if (!scene || !el || !layout) return;

      // Refresh the interactive hit rectangles from the latest scene.
      layout.modules = hitModules(scene);

      // Draw the scene into the buffer, then blit it up with nearest-neighbor.
      renderStation(bctx!, scene, stars, now, !!reduceMotion);

      const c = el.getContext("2d");
      if (!c) return;
      c.imageSmoothingEnabled = false;
      c.fillStyle = scene.palette.bg;
      c.fillRect(0, 0, el.width, el.height);
      c.drawImage(buffer, layout.offsetX, layout.offsetY, VW * layout.scale, VH * layout.scale);
    }

    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    // DPR can change when a window moves between monitors.
    const mq = window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`);
    mq.addEventListener?.("change", resize);
    const onVis = () => {
      if (!document.hidden) lastFrame = 0; // redraw promptly on refocus
    };
    document.addEventListener("visibilitychange", onVis);

    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      mq.removeEventListener?.("change", resize);
      document.removeEventListener("visibilitychange", onVis);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
