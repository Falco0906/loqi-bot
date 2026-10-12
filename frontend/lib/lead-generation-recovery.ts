import type { LeadStrategyGeneration } from "./api";

/** Recovery keys are user input too: a saved job must match this selection,
 * even before any results have been checkpointed.
 */
export function generationMatchesSelection(state: LeadStrategyGeneration, ids: string[]) {
  const actual = state.lead_ids;
  return Array.isArray(actual) && JSON.stringify([...actual].sort()) === JSON.stringify([...ids].sort());
}

/** Bounded, read-only observation. A paused observer never cancels its job. */
export async function observeLeadGeneration(
  read: () => Promise<LeadStrategyGeneration>,
  update: (state: LeadStrategyGeneration) => void,
  signal: AbortSignal,
  attempts = 30,
  intervalMs = 2000,
): Promise<"terminal" | "paused"> {
  for (let attempt = 0; attempt < attempts; attempt++) {
    if (signal.aborted) return "paused";
    try {
      const state = await read();
      if (signal.aborted) return "paused";
      update(state);
      if (!["queued", "running"].includes(state.status)) return "terminal";
    } catch (error) {
      if (signal.aborted) return "paused";
      if (!(error instanceof Error) || !["ApiError", "TimeoutError", "NetworkError"].includes(error.name)) throw error;
      if (error.name === "ApiError" && "status" in error && Number(error.status) < 500) throw error;
      // A failed status read does not prove that generation failed.
    }
    if (attempt + 1 < attempts) await new Promise<void>((resolve) => {
      const finish = () => { clearTimeout(timer); signal.removeEventListener("abort", finish); resolve(); };
      const timer = setTimeout(finish, intervalMs);
      signal.addEventListener("abort", finish, { once: true });
    });
  }
  return "paused";
}
