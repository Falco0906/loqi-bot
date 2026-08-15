/**
 * Draft lifecycle bucketing — single source of truth for which durable draft
 * statuses belong in which Draft Review section.
 *
 * The durable draft status (from the backend workspace store) is the source
 * of truth. A "sent" draft can never appear in an actionable bucket.
 */

export type DraftBucket = "pending" | "approved" | "sent" | null;

/** Statuses that carry a send/schedule action (approve → send/schedule). */
export const ACTIONABLE_STATUSES = new Set([
  "pending",
  "needs_review",
  "approved",
  "auto_approved",
  "scheduled",
]);

/** Statuses that can be approved/unapproved by the user. */
export const APPROVABLE_STATUSES = new Set([
  "pending",
  "needs_review",
  "approved",
]);

/**
 * Map a durable draft status to exactly one Draft Review section.
 * Returns null for statuses that are not shown in the queue sections
 * (rejected / failed / cancelled / archived).
 */
export function draftBucket(status: string): DraftBucket {
  if (status === "pending" || status === "needs_review") return "pending";
  if (
    status === "approved" ||
    status === "auto_approved" ||
    status === "scheduled"
  ) {
    return "approved";
  }
  if (status === "sent") return "sent";
  return null;
}

/** A sent draft is never actionable: no Approve, no Send Now, no Schedule. */
export function isActionable(status: string): boolean {
  return ACTIONABLE_STATUSES.has(status);
}

/** A sent draft can never be (re-)approved. */
export function isApprovable(status: string): boolean {
  return APPROVABLE_STATUSES.has(status);
}

/** Whether this status represents a durable "already sent" terminal action. */
export function isSentStatus(status: string): boolean {
  return status === "sent" || status === "sending";
}
