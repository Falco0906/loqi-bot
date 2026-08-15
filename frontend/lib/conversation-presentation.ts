/**
 * Shared conversation presentation helpers.
 *
 * Single source of truth for how conversations are labeled, tinted and
 * timestamped across the Inbox list and the conversation workspace, so both
 * always speak the same visual language.
 */

export const CLASSIFICATION_LABELS: Record<string, string> = {
  interested: "Interested",
  question: "Question",
  pricing_request: "Pricing",
  meeting_request: "Meeting Request",
  referral: "Referral",
  out_of_office: "OOO",
  bounce: "Bounce",
  auto_reply: "Auto Reply",
  not_interested: "Not Interested",
  unknown: "Unknown",
};

export const CLASSIFICATION_TONES: Record<string, string> = {
  interested: "bg-green-500/15 text-green-400",
  meeting_request: "bg-teal-500/15 text-teal-400",
  pricing_request: "bg-blue-500/15 text-blue-400",
  referral: "bg-violet-500/15 text-violet-400",
  question: "bg-amber-500/15 text-amber-400",
  follow_up: "bg-purple-500/15 text-purple-400",
  bounce: "bg-red-500/15 text-red-400",
  not_interested: "bg-surface-high/40 text-on-surface-variant/60",
  out_of_office: "bg-surface-high/40 text-on-surface-variant/60",
  auto_reply: "bg-surface-high/40 text-on-surface-variant/60",
  unknown: "bg-surface-high/40 text-on-surface-variant/60",
};

export const STATUS_FALLBACK_CLASS: Record<string, string> = {
  bounced: "bounce",
  follow_up_ready: "follow_up",
  follow_up_pending: "follow_up",
  interested: "interested",
};

export function classificationOf(row: {
  classification: string;
  status: string;
}): string {
  if (row.classification && row.classification !== "unknown") {
    return row.classification;
  }
  return STATUS_FALLBACK_CLASS[row.status] || row.classification || "";
}

export function classLabel(classification: string): string {
  return CLASSIFICATION_LABELS[classification] || classification || "";
}

export function classTone(classification: string): string {
  return CLASSIFICATION_TONES[classification] || CLASSIFICATION_TONES.unknown;
}

const NEEDS_ATTENTION_CLASSES = new Set([
  "interested",
  "pricing_request",
  "meeting_request",
  "referral",
  "question",
  "follow_up",
]);

export function attentionTone(classification: string): string {
  if (classification === "bounce") return "bg-red-500";
  if (NEEDS_ATTENTION_CLASSES.has(classification)) return "bg-primary";
  return "";
}

export function statusLabel(status: string): string {
  return (status || "").replace(/_/g, " ");
}

export function relativeTime(iso: string): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const minutes = Math.floor((Date.now() - t) / 60000);
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d`;
  return `${Math.floor(days / 7)}w`;
}

export function shortTime(iso: string): string {
  if (!iso) return "";
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "";
  return t.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}