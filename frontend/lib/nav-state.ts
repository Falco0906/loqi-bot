"use client";

/**
 * PR-3D — Navigation state layer.
 *
 * Answers a different question than the Phase-3C data cache:
 *   data cache  → "what data did we already fetch?"
 *   nav state   → "what was the user LOOKING at?"
 *
 * Stores small, serializable, non-sensitive UI facts per route:
 *   selected entity ids, filters, search strings, expanded sections.
 * Preserved across client-side navigation; cleared on identity boundaries
 * (logout/user switch) via clearNavState() from AuthContext.
 *
 * Bounded: max NAV_MAX_ENTRIES entries, oldest evicted. Every entry has a
 * TTL (default 30 minutes) so stale selections self-heal.
 */

const NAV_MAX_ENTRIES = 100;
const DEFAULT_TTL_MS = 30 * 60 * 1000;

type Entry = { value: unknown; ts: number; ttl: number };

const store = new Map<string, Entry>();

function debugEnabled(): boolean {
  try {
    return localStorage.getItem("loqi_debug_cache") === "1";
  } catch {
    return false;
  }
}

export function navKey(resource: string, field: string): string {
  return `nav:${resource}:${field}`;
}

export function setNavState<T>(resource: string, field: string, value: T,
                                ttlMs: number = DEFAULT_TTL_MS): void {
  if (value === undefined) return;
  // Bounded memory: drop expired first, then oldest.
  if (store.size >= NAV_MAX_ENTRIES && !store.has(navKey(resource, field))) {
    const now = Date.now();
    for (const [k, e] of store) {
      if (e.ts + e.ttl <= now) store.delete(k);
    }
    while (store.size >= NAV_MAX_ENTRIES) {
      store.delete(store.keys().next().value as string);
    }
  }
  store.set(navKey(resource, field), { value, ts: Date.now(), ttl: ttlMs });
}

export function getNavState<T>(resource: string, field: string): T | null {
  const key = navKey(resource, field);
  const entry = store.get(key);
  if (!entry) return null;
  if (entry.ts + entry.ttl <= Date.now()) {
    store.delete(key);
    return null;
  }
  return entry.value as T;
}

/** Read-and-forget: returns the value and clears it (one-shot restores). */
export function takeNavState<T>(resource: string, field: string): T | null {
  const value = getNavState<T>(resource, field);
  if (value !== null) store.delete(navKey(resource, field));
  return value;
}

export function clearNavState(resource?: string): void {
  if (!resource) {
    store.clear();
    return;
  }
  const prefix = `nav:${resource}:`;
  for (const key of [...store.keys()]) {
    if (key.startsWith(prefix)) store.delete(key);
  }
}
