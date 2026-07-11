import Link from "next/link";
import Icon from "../shared/Icon";
import CampaignStatusBadge from "./CampaignStatusBadge";

type Props = {
  id: string;
  name: string;
  status: string;
  leadCount: number;
  pendingDrafts: number;
  approvedDrafts: number;
  createdAt: string;
  updatedAt: string;
  onContinue?: () => void;
  onGenerate?: () => void;
  onArchive?: () => void;
  onDelete?: () => void;
};

function timeAgo(iso: string): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60000) return "just now";
  if (ms < 3600000) return `${Math.floor(ms / 60000)}m ago`;
  if (ms < 86400000) return `${Math.floor(ms / 3600000)}h ago`;
  return `${Math.floor(ms / 86400000)}d ago`;
}

export default function CampaignCard({
  id,
  name,
  status,
  leadCount,
  pendingDrafts,
  approvedDrafts,
  createdAt,
  updatedAt,
  onContinue,
  onGenerate,
  onArchive,
}: Props) {
  return (
    <Link
      href={`/campaigns/${id}`}
      className="block rounded-2xl border border-outline-variant/10 bg-surface-lowest p-5 transition-all hover:border-primary/20 hover:shadow-lg hover:-translate-y-0.5"
    >
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
            <Icon name="campaign" className="text-primary text-lg" />
          </div>
          <div className="min-w-0">
            <h3 className="text-body-lg text-on-surface font-bold truncate">{name}</h3>
            <p className="text-label-sm text-on-surface-variant/60">
              Created {timeAgo(createdAt)}
            </p>
          </div>
        </div>
        <CampaignStatusBadge status={status} />
      </div>

      <div className="flex items-center gap-5 mb-4">
        <div className="text-center">
          <p className="text-headline-sm text-on-surface font-bold">{leadCount}</p>
          <p className="text-label-sm text-on-surface-variant/60">{leadCount === 1 ? "Lead" : "Leads"}</p>
        </div>
        <div className="w-px h-8 bg-outline-variant/10" />
        <div className="text-center">
          <p className="text-headline-sm text-on-surface font-bold">{pendingDrafts}</p>
          <p className="text-label-sm text-on-surface-variant/60">Pending</p>
        </div>
        <div className="w-px h-8 bg-outline-variant/10" />
        <div className="text-center">
          <p className="text-headline-sm text-on-surface font-bold">{approvedDrafts}</p>
          <p className="text-label-sm text-on-surface-variant/60">Approved</p>
        </div>
        <div className="w-px h-8 bg-outline-variant/10" />
        <div className="text-center">
          <p className="text-label-sm text-on-surface-variant/40">
            {timeAgo(updatedAt) || "just now"}
          </p>
          <p className="text-label-sm text-on-surface-variant/60">Updated</p>
        </div>
      </div>

      <div className="flex items-center gap-2 pt-3 border-t border-outline-variant/10">
        <button
          onClick={(e) => { e.preventDefault(); onContinue?.(); }}
          className="px-3 py-1.5 rounded-lg bg-primary text-on-primary text-xs font-bold hover:brightness-110 transition-all"
        >
          Open
        </button>
        <button
          onClick={(e) => { e.preventDefault(); onGenerate?.(); }}
          className="px-3 py-1.5 rounded-lg border border-outline-variant/20 text-on-surface text-xs font-medium hover:border-primary/40 hover:text-primary transition-all"
        >
          Generate Drafts
        </button>
        <button
          onClick={(e) => { e.preventDefault(); onArchive?.(); }}
          className="px-3 py-1.5 rounded-lg border border-outline-variant/20 text-on-surface-variant/60 text-xs font-medium hover:border-error/40 hover:text-error transition-all ml-auto"
        >
          Archive
        </button>
      </div>
    </Link>
  );
}
