"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import Icon from "../shared/Icon";
import CampaignStatusBadge from "./CampaignStatusBadge";
import { toast } from "../shared/Toast";

type Props = {
  id: string;
  name: string;
  status: string;
  step?: string;
  leadCount: number;
  pendingDrafts: number;
  approvedDrafts: number;
  createdAt: string;
  updatedAt: string;
  onArchive?: () => void;
  onUnarchive?: () => void;
  onDelete?: () => void;
  onRename?: () => void;
  onDuplicate?: () => void;
};

function timeAgo(iso: string): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60000) return "just now";
  if (ms < 3600000) return `${Math.floor(ms / 60000)}m ago`;
  if (ms < 86400000) return `${Math.floor(ms / 3600000)}h ago`;
  return `${Math.floor(ms / 86400000)}d ago`;
}

const STEP_ACTIONS: Record<string, { primary: string; link: (id: string) => string }> = {
  research: { primary: "Research Prospects", link: (id) => `/campaigns/${id}` },
  strategy: { primary: "Generate Strategy", link: (id) => `/campaigns/${id}` },
  drafts: { primary: "Generate Drafts", link: (id) => `/campaigns/${id}` },
  review: { primary: "Review Drafts", link: (id) => `/draft?campaign=${encodeURIComponent(id)}` },
  sending: { primary: "Launch Campaign", link: (id) => `/campaigns/${id}` },
};

export default function CampaignCard({
  id,
  name,
  status,
  step,
  leadCount,
  pendingDrafts,
  approvedDrafts,
  createdAt,
  updatedAt,
  onArchive,
  onUnarchive,
  onDelete,
  onRename,
  onDuplicate,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const stepAction = STEP_ACTIONS[step || ""] || (status === "planning" ? STEP_ACTIONS.research : null);

  const primaryAction = (() => {
    if (status === "archived") {
      return (
        <Link
          href={`/campaigns/${id}`}
          className="px-3 py-1.5 rounded-lg bg-primary text-on-primary text-xs font-bold transition-all duration-150 hover:brightness-110 active:scale-[0.95]"
        >
          View Campaign
        </Link>
      );
    }
    if (step === "review") {
      return (
        <Link
          href={stepAction?.link(id) || `/draft?campaign=${encodeURIComponent(id)}`}
          className="px-3 py-1.5 rounded-lg bg-secondary text-on-primary text-xs font-bold transition-all duration-150 hover:brightness-110 active:scale-[0.95]"
        >
          {stepAction?.primary || "Review Drafts"}
        </Link>
      );
    }
    if (step === "sending") {
      return (
        <Link
          href={stepAction?.link(id) || `/campaigns/${id}`}
          className="px-3 py-1.5 rounded-lg bg-primary text-on-primary text-xs font-bold transition-all duration-150 hover:brightness-110 active:scale-[0.95]"
        >
          <Icon name="rocket_launch" className="text-xs mr-1 align-middle inline-block" />
          {stepAction?.primary || "Launch Campaign"}
        </Link>
      );
    }
    return (
      <Link
        href={stepAction?.link(id) || `/campaigns/${id}`}
        className="px-3 py-1.5 rounded-lg bg-primary text-on-primary text-xs font-bold transition-all duration-150 hover:brightness-110 active:scale-[0.95]"
      >
        {stepAction?.primary || "Continue Planning"}
      </Link>
    );
  })();

  const secondaryAction = (() => {
    if (status !== "archived" && (step === "review" || step === "sending")) {
      return (
        <Link
          href={`/campaigns/${id}`}
          className="px-3 py-1.5 rounded-lg border border-outline-variant/20 text-on-surface text-xs font-medium transition-all duration-150 hover:border-primary/40 hover:text-primary active:scale-[0.95]"
        >
          Campaign Details
        </Link>
      );
    }
    return null;
  })();

  return (
    <div className="block card-interactive p-5">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
            <Icon name="campaign" className="text-primary text-lg" />
          </div>
          <div className="min-w-0">
            <Link href={`/campaigns/${id}`} className="hover:underline">
              <h3 className="text-body-lg text-on-surface font-bold truncate">{name}</h3>
            </Link>
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
          <p className="text-label-sm text-on-surface-variant/60">Leads</p>
        </div>
        <div className="w-px h-8 bg-outline-variant/10" />
        <div className="text-center">
          <p className="text-headline-sm text-on-surface font-bold">{pendingDrafts}</p>
          <p className="text-label-sm text-on-surface-variant/60">Drafts Pending</p>
        </div>
        <div className="w-px h-8 bg-outline-variant/10" />
        <div className="text-center">
          <p className="text-headline-sm text-on-surface font-bold">{approvedDrafts}</p>
          <p className="text-label-sm text-on-surface-variant/60">Drafts Approved</p>
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
        {primaryAction}
        {secondaryAction}

        {/* Overflow menu */}
        <div className="relative ml-auto" ref={menuRef}>
          <button
            onClick={(e) => { e.preventDefault(); setMenuOpen((prev) => !prev); }}
            className="p-1.5 rounded-lg text-on-surface-variant/50 hover:text-on-surface hover:bg-surface-high/60 transition-all"
            aria-label="Campaign actions"
          >
            <Icon name="more_horiz" className="text-lg" />
          </button>

          {menuOpen && (
            <div
              className="absolute right-0 top-full mt-1 w-44 rounded-xl border border-outline-variant/10 bg-surface-lowest shadow-xl py-1 z-50 animate-scale-in"
              onClick={(e) => e.preventDefault()}
            >
              <button
                onClick={() => { setMenuOpen(false); onRename?.(); }}
                className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-on-surface hover:bg-surface/60 transition-all"
              >
                <Icon name="edit_note" className="text-sm text-on-surface-variant" />
                Rename
              </button>
              <button
                onClick={() => { setMenuOpen(false); onDuplicate?.(); }}
                className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-on-surface hover:bg-surface/60 transition-all"
              >
                <Icon name="add_circle" className="text-sm text-on-surface-variant" />
                Duplicate
              </button>
              {status === "archived" ? (
                <button
                  onClick={() => { setMenuOpen(false); onUnarchive?.(); toast("success", "Campaign restored"); }}
                  className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-on-surface hover:bg-surface/60 transition-all"
                >
                  <Icon name="refresh" className="text-sm text-on-surface-variant" />
                  Unarchive
                </button>
              ) : (
                <button
                  onClick={() => { setMenuOpen(false); onArchive?.(); toast("success", "Campaign archived"); }}
                  className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-on-surface hover:bg-surface/60 transition-all"
                >
                  <Icon name="folder_zip" className="text-sm text-on-surface-variant" />
                  Archive
                </button>
              )}
              <hr className="border-outline-variant/10 my-1" />
              <button
                onClick={() => { setMenuOpen(false); onDelete?.(); }}
                className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-error hover:bg-error/5 transition-all"
              >
                <Icon name="close" className="text-sm" />
                Delete
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
