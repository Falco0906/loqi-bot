/**
 * PR-3D-FIX — pure campaign filtering/counting.
 *
 * Contract:
 *  - An empty/whitespace query means "show everything".
 *  - Filtering NEVER mutates the canonical array.
 *  - Counts come from the canonical dataset, not the filtered view.
 */

export type CampaignLike = {
  status?: string | null;
  name?: string | null;
  objective?: string | null;
};

export function normalizeQuery(q: string | null | undefined): string {
  return (q ?? "").trim().toLowerCase();
}

/** Pure derivation. Canonical input is never mutated. */
export function filterCampaigns<T extends CampaignLike>(campaigns: readonly T[], query: string): T[] {
  const q = normalizeQuery(query);
  return campaigns.filter(c => {
    if (c.status === "deleted") return false;
    if (!q) return true;
    const name = String(c.name ?? "").toLowerCase();
    const objective = String(c.objective ?? "").toLowerCase();
    return name.includes(q) || objective.includes(q);
  });
}

/** Header count: canonical total (never the filtered subset). */
export function canonicalTotal<T extends CampaignLike>(campaigns: readonly T[]): number {
  return campaigns.filter(c => c.status !== "deleted").length;
}

/** The ONLY conditions under which "No campaigns match" may render. */
export function shouldShowNoMatches(
  opts: { authoritativeDataLoaded: boolean; canonicalCount: number; query: string; filteredCount: number },
): boolean {
  return (
    opts.authoritativeDataLoaded &&
    opts.canonicalCount > 0 &&
    normalizeQuery(opts.query) !== "" &&
    opts.filteredCount === 0
  );
}
