import Link from "next/link";
import CampaignStatusBadge from "./CampaignStatusBadge";
import Icon from "../shared/Icon";

type Props = {
  id: string;
  name: string;
  status: string;
  pendingDrafts: number;
  leadCount: number;
};

const statusLabels: Record<string, string> = {
  planning: "Strategy awaiting approval",
  ready: "Ready to start drafting",
  generating: "Drafts being generated",
  draft_review: "drafts pending review",
  ready_to_send: "Ready to send",
  completed: "Completed",
  archived: "Archived",
};

export default function ContinueWorkingCard({ id, name, status, pendingDrafts, leadCount }: Props) {
  const label = status === "draft_review"
    ? `${pendingDrafts} ${statusLabels[status]}`
    : (statusLabels[status] || status);

  return (
    <Link
      href={`/campaigns/${id}`}
      className="group flex items-center justify-between rounded-xl border border-outline-variant/10 bg-surface-lowest px-5 py-4 transition-all hover:border-primary/20"
    >
      <div className="flex items-center gap-4 min-w-0">
        <div className="w-9 h-9 rounded-lg bg-primary-container/10 flex items-center justify-center shrink-0">
          <Icon name="campaign" className="text-primary text-base" />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <p className="text-body-md text-on-surface font-bold truncate">{name}</p>
            <CampaignStatusBadge status={status} />
          </div>
          <p className="text-label-sm text-on-surface-variant/60">
            {leadCount} {leadCount === 1 ? "lead" : "leads"} &middot; {label}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0 ml-3">
        <span className="text-label-sm text-primary font-medium opacity-0 group-hover:opacity-100 transition-opacity">
          Continue
        </span>
        <Icon name="chevron_right" className="text-primary" />
      </div>
    </Link>
  );
}
