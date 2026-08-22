"use client";

/**
 * PR-3C — lightweight client-side data cache with stale-while-revalidate.
 *
 * Semantics:
 *   fresh  (< TTL)  → return cached value immediately, NO network
 *   stale  (≥ TTL)  → serve cached value via opts.onStale, revalidate in
 *                     background (deduplicated), deliver fresh via onUpdate
 *   miss            → single network fetch
 *
 * Bounded memory (MAX_ENTRIES, oldest-evicted). Session-scoped keys keep
 * users/workspaces isolated; clearClientCache() runs on logout/credential
 * resets. No tokens or credentials are ever stored here — values are API
 * payloads the UI already renders.
 *
 * Instrumentation: set localStorage "loqi_debug_cache" = "1" to see
 * [data-cache] hit/miss/revalidate/deduped/invalidate lines.
 */

type Entry = { value: unknown; ts: number };

const store = new Map<string, Entry>();
const inflight = new Map<string, Promise<unknown>>();

export const CACHE_TTL_MS_DEFAULT = 10_000;
const MAX_ENTRIES = 60;

function debugEnabled(): boolean {
  try {
    return localStorage.getItem("loqi_debug_cache") === "1";
  } catch {
    return false;
  }
}

function debug(msg: string): void {
  if (debugEnabled()) console.debug(`[data-cache] ${msg}`);
}

/** Build a session-scoped cache key. The active web-session token scopes all
 * entries per login; it is used only as a key component, never stored as a
 * value. */
export function scopedKey(sessionToken: string | null | undefined, resource: string,
                          ...params: (string | number | undefined)[]): string {
  const parts = [resource, sessionToken || "anonymous", ...params.map(p => String(p))];
  return parts.join(":");
}

export function cacheAge(key: string): number | null {
  const entry = store.get(key);
  if (!entry) return null;
  return (Date.now() - entry.ts) / 1000;
}

export function peekCache<T>(key: string): { value: T } | null {
  const entry = store.get(key);
  if (!entry) return null;
  return { value: entry.value as T };
}

export function invalidateClientCache(prefix: string): void {
  let n = 0;
  for (const key of [...store.keys()]) {
    if (key.startsWith(prefix)) {
      store.delete(key);
      inflight.delete(key);
      n += 1;
    }
  }
  if (n && debugEnabled()) debug(`invalidate prefix=${prefix} entries=${n}`);
}

export function clearClientCache(): void {
  store.clear();
  inflight.clear();
  if (debugEnabled()) debug("clear-all");
}

function evictIfNeeded(): void {
  while (store.size > MAX_ENTRIES) {
    let oldestKey = "";
    let oldestTs = Infinity;
    for (const [key, entry] of store) {
      if (entry.ts < oldestTs) {
        oldestTs = entry.ts;
        oldestKey = key;
      }
    }
    if (!oldestKey) break;
    store.delete(oldestKey);
  }
}

export type SwrOptions<T> = {
  /** Serve this cached (possibly stale) value immediately on stale hits. */
  onStale?: (value: T) => void;
  /** Deliver the fresh value after background/network completion. */
  onUpdate?: (value: T) => void;
  ttlMs?: number;
};

export async function swrFetch<T>(
  key: string,
  fetcher: () => Promise<T>,
  opts: SwrOptions<T> = {},
): Promise<T> {
  const ttl = opts.ttlMs ?? CACHE_TTL_MS_DEFAULT;

  const entry = store.get(key);
  if (entry) {
    const age = (Date.now() - entry.ts) / 1000;
    if (age * 1000 < ttl) {
      debug(`${key} hit age=${age.toFixed(1)}s`);
      return entry.value as T;
    }
    // Stale: serve immediately, then revalidate below (deduplicated).
    debug(`${key} revalidate age=${age.toFixed(1)}s`);
    opts.onStale?.(entry.value as T);
  }

  const existing = inflight.get(key);
  if (existing) {
    debug(`${key} deduped`);
    return (await existing) as T;
  }

  const promise = (async () => {
    const value = await fetcher();
    store.set(key, { value, ts: Date.now() });
    evictIfNeeded();
    return value;
  })();
  const clear = () => inflight.delete(key);
  inflight.set(key, promise as Promise<unknown>);
  void promise.then(clear, clear); // always remove from dedup map once settled

  if (entry) {
    // Stale revalidation: the caller already rendered the cached value.
    // A refresh failure must NOT reject into their error handling — keep
    // serving the known-good data (spec §error-handling).
    try {
      const value = (await promise) as T;
      opts.onUpdate?.(value);
      return value;
    } catch (error) {
      debug(`${key} refresh-failed keeping-stale`);
      return entry.value as T;
    }
  }

  const value = (await promise) as T; // miss → errors propagate (existing UX)
  opts.onUpdate?.(value);
  return value;
}

/** Test seam: inject synthetic time offsets / reset state. */
export function __testReset(): void {
  store.clear();
  inflight.clear();
}

export function __testAgeEntry(key: string, seconds: number): void {
  const entry = store.get(key);
  if (entry) entry.ts -= seconds * 1000;
}
