"use client";

// Galaxia Command — swipe-to-decide.
//
// The founder decision inbox as a card deck: swipe (or drag) the top card right
// to approve, left to reject. Everything the gesture does is also available as
// real buttons underneath, so keyboard/AT users are never locked out. Reuses the
// existing approve/reject flow and the app's `.decision-panel` styling.

import { useEffect, useRef, useState } from "react";
import { api, decisionKindLabel, type Decision } from "@/lib/api";
import { Markdown } from "@/lib/markdown";

const THRESHOLD = 90; // px of horizontal travel to commit
const V_MIN = 0.5; // px/ms flick velocity to commit regardless of distance

export function SwipeDeck({
  decisions,
  onResolved,
  showEmpty = true,
}: {
  decisions: Decision[];
  onResolved: () => void;
  // When false, render nothing instead of the "all clear" line — the caller is
  // showing another kind of pending item (e.g. a chat reply) and shouldn't be
  // contradicted by "no orders pending".
  showEmpty?: boolean;
}) {
  // Locally hide optimistically-resolved cards until the parent poll catches up.
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const pending = decisions.filter(
    (d) => (d.status === "pending" || d.status === "waiting_approval") && !removed.has(d.id),
  );

  const resolve = async (d: Decision, approve: boolean) => {
    if (resolvingId) return;
    setResolvingId(d.id);
    setRemoved((prev) => new Set(prev).add(d.id)); // optimistic
    try {
      if (approve) await api.approveDecision(d.id);
      else await api.rejectDecision(d.id);
    } catch {
      // Restore on failure so the founder can retry.
      setRemoved((prev) => {
        const next = new Set(prev);
        next.delete(d.id);
        return next;
      });
    } finally {
      setResolvingId(null);
      setExpanded(false);
      onResolved();
    }
  };

  if (pending.length === 0) {
    if (!showEmpty) return null;
    return <p className="muted" style={{ marginTop: 10 }}>All clear, Captain. No orders pending.</p>;
  }

  // Render up to 3 cards; only the top is interactive. Later cards peek behind.
  const stack = pending.slice(0, 3);
  return (
    <div className="swipe-deck" style={{ marginTop: 10 }}>
      {/* Top card first in DOM so it's position:relative and sizes the deck;
          the peeking cards behind are absolutely positioned (z-index paints the
          top card above them regardless of DOM order). */}
      {stack.map((d, i) => (
        <SwipeCard
          key={d.id}
          decision={d}
          depth={i}
          interactive={i === 0}
          busy={resolvingId === d.id}
          expanded={i === 0 && expanded}
          onToggleExpand={() => setExpanded((v) => !v)}
          onResolve={(approve) => resolve(d, approve)}
        />
      ))}
      <p className="muted swipe-hint">
        Swipe right to approve · left to reject{pending.length > 1 ? ` · ${pending.length} pending` : ""}
      </p>
    </div>
  );
}

function SwipeCard({
  decision,
  depth,
  interactive,
  busy,
  expanded,
  onToggleExpand,
  onResolve,
}: {
  decision: Decision;
  depth: number;
  interactive: boolean;
  busy: boolean;
  expanded: boolean;
  onToggleExpand: () => void;
  onResolve: (approve: boolean) => void;
}) {
  const cardRef = useRef<HTMLDivElement | null>(null);
  const drag = useRef<{ startX: number; startT: number; dx: number; active: boolean }>({
    startX: 0, startT: 0, dx: 0, active: false,
  });
  const [dx, setDx] = useState(0);
  const [flyOff, setFlyOff] = useState<0 | 1 | -1>(0);

  const reduce =
    typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  // Reset transient drag state if this card becomes the top card.
  useEffect(() => {
    setDx(0);
    setFlyOff(0);
    drag.current = { startX: 0, startT: 0, dx: 0, active: false };
  }, [decision.id]);

  const commit = (approve: boolean) => {
    if (reduce) { onResolve(approve); return; }
    setFlyOff(approve ? 1 : -1);
    // Let the fly-off transition play, then resolve.
    window.setTimeout(() => onResolve(approve), 180);
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (!interactive || busy) return;
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    drag.current = { startX: e.clientX, startT: e.timeStamp, dx: 0, active: true };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current.active) return;
    const d = e.clientX - drag.current.startX;
    drag.current.dx = d;
    setDx(d);
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (!drag.current.active) return;
    const d = drag.current.dx;
    const v = d / Math.max(1, e.timeStamp - drag.current.startT);
    drag.current.active = false;
    if (Math.abs(d) < 6) {
      // A tap, not a swipe → toggle detail.
      onToggleExpand();
      setDx(0);
      return;
    }
    if (Math.abs(d) > THRESHOLD || Math.abs(v) > V_MIN) {
      commit(d > 0);
    } else {
      setDx(0); // spring back (CSS transition on .swipe-card)
    }
  };

  // Keyboard operability replaces the removed buttons: arrow keys decide, and
  // Enter/Space toggles detail — so the deck stays usable without a pointer.
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!interactive || busy) return;
    if (e.key === "ArrowRight") { e.preventDefault(); commit(true); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); commit(false); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggleExpand(); }
  };

  const shownDx = flyOff !== 0 ? flyOff * (cardRef.current?.offsetWidth ?? 400) * 1.3 : dx;
  const rot = shownDx * 0.04;
  const dragging = drag.current.active;
  const springing = !dragging && flyOff === 0; // enable transition on release
  const tint = Math.min(1, Math.abs(dx) / THRESHOLD);
  // Idle nudge hints the card is draggable — off once the user grabs it.
  const idle = interactive && !dragging && flyOff === 0 && dx === 0;

  return (
    <div
      ref={cardRef}
      className={`swipe-card${springing ? " swipe-springback" : ""}${idle ? " swipe-nudge" : ""}${interactive ? " swipe-top" : ""}`}
      role="group"
      tabIndex={interactive ? 0 : -1}
      aria-label={`Decision: ${decisionKindLabel(decision.kind)}. Swipe right or press Right Arrow to approve, left to reject.`}
      aria-busy={busy}
      onKeyDown={onKeyDown}
      style={{
        transform: `translateX(${shownDx}px) rotate(${rot}deg)`,
        // peeking cards sit slightly scaled/lowered behind the top card
        ...(interactive
          ? { zIndex: 3 }
          : { zIndex: 3 - depth, transform: `translateY(${depth * 8}px) scale(${1 - depth * 0.04})`, opacity: 1 - depth * 0.15 }),
      }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => { drag.current.active = false; setDx(0); }}
    >
      {interactive && (
        <>
          <span className="swipe-badge approve" style={{ opacity: dx > 0 ? tint : 0 }} aria-hidden>
            ✓ APPROVE
          </span>
          <span className="swipe-badge reject" style={{ opacity: dx < 0 ? tint : 0 }} aria-hidden>
            ✕ REJECT
          </span>
        </>
      )}
      <div className="decision-kind">
        {decisionKindLabel(decision.kind)}
        {decision.agent_name ? ` · ${decision.agent_name}` : ""}
        {decision.agent_role ? ` (${decision.agent_role})` : ""}
      </div>
      <Markdown className="decision-note">{decision.summary}</Markdown>
      {interactive && expanded && (decision.task_goal || decision.objective_title) && (
        <div className="swipe-detail muted">
          {decision.objective_title && <div>Objective: {decision.objective_title}</div>}
          {decision.task_goal && <div>Task: {decision.task_goal}</div>}
        </div>
      )}
      {interactive && (
        // Always-visible swipe affordances (no buttons) — the reject side lights
        // up as you drag left, the approve side as you drag right.
        <div className="swipe-affordance" aria-hidden>
          <span className="reject" style={{ opacity: dx < 0 ? 0.5 + tint * 0.5 : 0.55 }}>← Reject</span>
          <span className="grip">{busy ? "…" : "swipe to decide"}</span>
          <span className="approve" style={{ opacity: dx > 0 ? 0.5 + tint * 0.5 : 0.55 }}>Approve →</span>
        </div>
      )}
    </div>
  );
}
