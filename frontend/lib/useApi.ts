"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Task } from "./api";

/** Fetch on mount and optionally poll. Returns data, error, loading, reload. */
export function usePoll<T>(fn: () => Promise<T>, intervalMs = 0, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const result = await fn();
      setData(result);
      setError(null);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    let active = true;
    const run = async () => { if (active) await load(); };
    run();
    if (intervalMs > 0) {
      const id = setInterval(run, intervalMs);
      return () => { active = false; clearInterval(id); };
    }
    return () => { active = false; };
  }, [load, intervalMs]);

  return { data, error, loading, reload: load };
}

/** Live company task feed: SSE when it's healthy, polling otherwise.
 *
 * Why this isn't just `streamed ?? polled`: once the SSE delivered a single
 * frame, that naive expression pins the UI to it forever — so any later
 * disconnect (EventSource doesn't auto-reconnect after we close on error),
 * proxy stall, or laptop sleep freezes the feed on a stale snapshot while the
 * poll fallback's fresh data is silently ignored. Instead we trust the stream
 * only while it is BOTH healthy and has actually delivered a frame, and keep a
 * poll running in every other case (errored, or connected-but-not-yet-streaming,
 * e.g. a buffering proxy), so the feed always keeps refreshing.
 */
export function useLiveTasks(companyId: string): Task[] {
  const [streamed, setStreamed] = useState<Task[] | null>(null);
  const [sseOk, setSseOk] = useState(true);
  // Flips false→true once and stays, so SSE frames don't re-create the poller
  // (and reset its interval) on every snapshot.
  const streamReady = streamed !== null;
  const streaming = sseOk && streamReady;
  // Poll whenever the stream isn't actively delivering. usePoll still fetches
  // once on mount even at interval 0, so there's an immediate fallback snapshot.
  const polled = usePoll(
    () => api.tasks(companyId),
    streaming ? 0 : 5000,
    [companyId, streaming],
  );

  useEffect(() => {
    const url = api.eventsUrl(companyId);
    if (typeof window === "undefined" || typeof EventSource === "undefined" || !url) {
      setSseOk(false);
      return;
    }
    setSseOk(true);
    setStreamed(null);
    const es = new EventSource(url);
    es.onmessage = (e: MessageEvent) => {
      try {
        setStreamed((JSON.parse(e.data) as { tasks: Task[] }).tasks);
        setSseOk(true);
      } catch {
        /* ignore malformed frame */
      }
    };
    es.onerror = () => {
      // We don't let EventSource auto-reconnect (it would spin on a hard error);
      // closing flips us to polling, which recovers and is cheap enough.
      es.close();
      setSseOk(false);
    };
    return () => es.close();
  }, [companyId]);

  return streaming && streamed ? streamed : (polled.data ?? []);
}
