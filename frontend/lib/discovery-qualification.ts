export type PersistedQualification = Record<string, unknown>;

/** Parse workspace_leads.metadata, which Supabase may return as JSON text. */
export function qualificationFromPersistedMetadata(value: unknown): PersistedQualification | null {
  const record = typeof value === "string" ? parseJson(value) : value;
  if (!record || typeof record !== "object" || Array.isArray(record)) return null;
  const qualification = (record as Record<string, unknown>).qualification;
  return qualification && typeof qualification === "object" && !Array.isArray(qualification)
    ? qualification as PersistedQualification
    : null;
}

function parseJson(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}
