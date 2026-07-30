"use client";

import type { Prospect } from "../../lib/types/prospect";
import Icon from "../shared/Icon";
import { useProspectRegistry } from "../../contexts/ProspectRegistryProvider";
import { toast } from "../shared/Toast";

function ScoreBadge({ score }: { score?: number }) {
  if (score == null) return null;
  const stars = Math.round((score / 150) * 5);
  return (
    <div className="flex text-tertiary">
      {Array.from({ length: 5 }, (_, i) => (
        <Icon key={i} name="star" className={`text-sm ${i < stars ? "opacity-100" : "opacity-30"}`} fill={i < stars} />
      ))}
    </div>
  );
}

type Props = {
  prospect: Prospect;
  selected?: boolean;
  onToggle?: (prospect: Prospect) => void;
  action?: "save" | "remove" | "none";
};

export default function ProspectCard({ prospect, selected, onToggle, action = "none" }: Props) {
  const { save, unsave, isSaved } = useProspectRegistry();
  const saved = isSaved(prospect.id);

  const handleAction = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (action === "save") {
        if (saved) {
            unsave(prospect.id);
            toast("success", "Removed from contacts");
        } else {
            save(prospect);
            toast("success", "Saved to contacts");
        }
    } else if (action === "remove") {
      unsave(prospect.id);
      toast("success", "Removed from contacts");
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onToggle?.(prospect)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle?.(prospect); } }}
      className={`rounded-xl p-4 cursor-pointer transition-all duration-150 select-none active:scale-[0.99] focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2 ${
        selected
          ? "border-2 border-primary/60 bg-surface-low"
          : "border border-outline-variant/10 bg-surface hover:bg-surface-low hover:border-outline-variant/30"
      }`}
    >
      <div className="flex justify-between items-start mb-3">
        <div className="flex gap-3 items-start">
          <div className="w-10 h-10 rounded-lg bg-[#1F1F23] flex items-center justify-center text-on-surface-variant/40 text-xs font-bold shrink-0">
            {prospect.contact.charAt(0).toUpperCase()}
          </div>
          <div>
            <h3 className="text-body-lg font-bold text-on-surface">{prospect.contact}</h3>
            <p className="text-on-surface-variant text-body-md">
              {prospect.title} • {prospect.company}
            </p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
            <ScoreBadge score={prospect.confidence} />
            {action !== "none" && (
            <button 
                onClick={handleAction}
                className={`text-sm font-medium transition-colors ${saved ? "text-secondary" : "text-primary hover:underline"}`}
            >
                {action === "save" ? (saved ? "Saved" : "Save") : "Remove"}
            </button>
            )}
        </div>
      </div>
      <div className="ml-12 space-y-3">
         <p className="text-on-surface-variant text-sm line-clamp-2">{prospect.summary}</p>
      </div>
    </div>
  );
}
