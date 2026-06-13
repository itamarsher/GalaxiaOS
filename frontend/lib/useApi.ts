"use client";

import { useCallback, useEffect, useState } from "react";

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
