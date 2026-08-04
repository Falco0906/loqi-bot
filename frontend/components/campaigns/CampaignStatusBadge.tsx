type Props = {
  status: string;
  className?: string;
};

const config: Record<string, { label: string; bg: string; text: string }> = {
  planning: { label: "Planning", bg: "bg-warning/10", text: "text-warning" },
  strategy_review: { label: "Strategy Review", bg: "bg-primary/10", text: "text-primary" },
  lead_selection: { label: "Lead Selection", bg: "bg-secondary/10", text: "text-secondary" },
  ready: { label: "Ready", bg: "bg-primary/10", text: "text-primary" },
  generating: { label: "Generating", bg: "bg-secondary/10", text: "text-secondary" },
  draft_review: { label: "Draft Review", bg: "bg-primary-container/20", text: "text-primary" },
  ready_to_send: { label: "Ready To Send", bg: "bg-success/10", text: "text-success" },
  completed: { label: "Completed", bg: "bg-success/10", text: "text-success" },
  archived: { label: "Archived", bg: "bg-outline-variant/10", text: "text-on-surface-variant/50" },
};

export default function CampaignStatusBadge({ status, className = "" }: Props) {
  const c = config[status] || { label: status, bg: "bg-surface-high", text: "text-on-surface-variant" };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider ${c.bg} ${c.text} ${className}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${c.text.replace("text-", "bg-")}`} />
      {c.label}
    </span>
  );
}
