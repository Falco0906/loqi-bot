/** Discovery navigation hints contain URLs, never results or credentials.
 * Durable runs and workspace_leads remain server-owned and reauthorized on read.
 */
export const DISCOVERY_CONTEXT_KEY = "loqi_active_discovery";

export function discoveryResponseIsCurrent(captured: { scope: string; revision: number }, current: { scope: string; revision: number }, mounted: boolean, signal: AbortSignal) {
  return mounted && !signal.aborted && captured.scope === current.scope && captured.revision === current.revision;
}

export function rememberDiscoveryContext(storage: Pick<Storage, "setItem">, scope: string, params: URLSearchParams) {
  if (!scope || !params.get("q")) return;
  storage.setItem(DISCOVERY_CONTEXT_KEY, JSON.stringify({ scope, search: params.toString() }));
}

export function restoredDiscoveryContext(storage: Pick<Storage, "getItem">, scope: string, current: URLSearchParams): string | null {
  // Explicit URLs (including campaign entry and fresh=1) always win.
  if (!scope || current.size) return null;
  try {
    const hint = JSON.parse(storage.getItem(DISCOVERY_CONTEXT_KEY) || "null");
    if (hint?.scope !== scope || typeof hint.search !== "string") return null;
    const params = new URLSearchParams(hint.search);
    return params.get("q") ? `/discovery?${params}` : null;
  } catch { return null; }
}

export function rememberedDiscoveryWorkspace(storage: Pick<Storage, "getItem">, identity: string, accessible: string[]) {
  try {
    const hint = JSON.parse(storage.getItem(DISCOVERY_CONTEXT_KEY) || "null");
    return accessible.find((workspace) => hint?.scope === `${identity}:${workspace}`) || "";
  } catch { return ""; }
}

/** Reuse the existing working URL only within the authorized page scope. */
export function discoveryReturnUrl(storage: Pick<Storage, "getItem">, scope: string, workspaceId: string) {
  const restored = restoredDiscoveryContext(storage, scope, new URLSearchParams());
  if (restored && new URLSearchParams(restored.split("?")[1]).get("workspace_id") === workspaceId) return restored;
  return `/discovery?workspace_id=${encodeURIComponent(workspaceId)}`;
}

/** Page is deliberately excluded: pagination retains the same selection. */
export function discoverySelectionScope(workspace: string, params: URLSearchParams) {
  return JSON.stringify([workspace, ...["q", "location", "industry", "company", "title", "keywords", "provider_discovery", "campaign_id"].map((key) => params.get(key) || "")]);
}

export function discoveryHistoryUrl(run: { id: string; query: string; metadata?: Record<string, unknown> }, workspaceId = "") {
  const params = new URLSearchParams({ q: run.query, page: "1", provider_discovery: run.id });
  if (workspaceId) params.set("workspace_id", workspaceId);
  Object.entries(discoverySavedFilters(run.metadata)).forEach(([key, value]) => params.set(key, value));
  return `/discovery?${params}`;
}

export function discoverySavedFilters(metadata?: Record<string, unknown>) {
  const values: Record<string, string> = {};
  const filters = metadata?.ui_filters;
  if (filters && typeof filters === "object") {
    for (const key of ["location", "industry", "company", "title", "keywords"]) {
      const value = (filters as Record<string, unknown>)[key];
      if (typeof value === "string" && value && value.length <= 200) values[key] = value;
    }
  }
  return values;
}
