"use client";

import { useEffect, useRef, useState, useCallback } from "react";

export type AsyncState<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
  /**
   * Trigger a refetch. Returns a promise that settles once the refetch has
   * completed (success or failure) — callers can await it to prevent
   * overlapping polls. Ignoring the returned promise remains fine.
   */
  retry: () => Promise<void>;
  /**
   * Patch the cached data in place so mutations never need a full page
   * reload. Accepts a value or an updater over the previous data.
   */
  mutate: (next: T | null | ((prev: T | null) => T | null)) => void;
};

/**
 * Data hook with an optional synchronous initial value (e.g. a cache peek).
 * When `initial` is provided the page renders that data immediately —
 * Copilot-navigated destinations appear fully formed instead of flashing
 * skeletons on arrival.
 *
 * `mutate` lets callers patch data after a mutation (no `location.reload`),
 * which preserves scroll position, keeps the sidebar mounted and avoids
 * skeleton flicker.
 */
export function useData<T>(
  fetcher: () => Promise<T | null>,
  options: { initial?: T | null } = {},
): AsyncState<T> {
  const hasInitial = options.initial !== undefined;
  const [data, setData] = useState<T | null>(options.initial ?? null);
  const [loading, setLoading] = useState(!hasInitial);
  const [error, setError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);

  // Tracks the most recent fetch attempt so retry() can serialize callers:
  // PR-P1.4 — polling loops awaiting this can never overlap requests.
  const inflightRef = useRef<Promise<void>>(Promise.resolve());

  const retry = useCallback(async (): Promise<void> => {
    // Wait out any fetch already in flight before triggering another.
    await inflightRef.current;
    setRetryCount((n) => n + 1);
    // Let React commit + run the effect that starts the new fetch, then
    // wait for it. Worst case under heavy batching we resolve one tick late.
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    await inflightRef.current;
  }, []);

  const mutate = useCallback((updater: T | null | ((prev: T | null) => T | null)) => {
    setData((prev) =>
      typeof updater === "function" ? (updater as (p: T | null) => T | null)(prev) : updater,
    );
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const attempt = fetcher()
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "An error occurred");
          setLoading(false);
        }
      });
    // Settle regardless of outcome/cancellation so retry() never hangs.
    inflightRef.current = attempt.then(
      () => undefined,
      () => undefined,
    );
    return () => { cancelled = true; };
  }, [fetcher, retryCount]);

  return { data, loading, error, retry, mutate };
}
