"use client";

import { useState } from "react";
import Icon from "../shared/Icon";

type Props = {
  count: number;
  onDraft: () => void;
  onSaveCampaign: () => void;
  onCompare: () => void;
  onExport: () => void;
  onClear: () => void;
};

export default function BatchActionBar({ count, onDraft, onSaveCampaign, onCompare, onExport, onClear }: Props) {
  const [exportOpen, setExportOpen] = useState(false);

  return (
    <div className="fixed bottom-8 left-1/2 -translate-x-1/2 z-50 animate-slide-up">
      <div className="glass-panel border border-outline-variant/20 px-6 py-4 rounded-2xl flex items-center gap-6 shadow-2xl">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-on-primary font-bold text-sm">
            {count}
          </div>
          <span className="font-bold text-on-surface whitespace-nowrap">
            {count} {count === 1 ? "Lead" : "Leads"} Selected
          </span>
        </div>

        <div className="h-8 w-px bg-outline-variant/20" />

        <div className="flex items-center gap-2">
          <button
            onClick={onDraft}
            className="px-5 py-2.5 bg-primary text-on-primary font-bold rounded-lg flex items-center gap-2 hover:brightness-110 active:scale-95 transition-all text-sm"
          >
            <Icon name="edit_note" className="text-base" />
            Draft Outreach
          </button>

          <button
            onClick={onSaveCampaign}
            className="px-4 py-2.5 border border-outline-variant/20 text-on-surface font-medium rounded-lg flex items-center gap-2 hover:border-primary/40 hover:text-primary active:scale-95 transition-all text-sm"
          >
            <Icon name="add_circle" className="text-base" />
            Save Campaign
          </button>

          <div className="relative">
            <button
              onClick={() => setExportOpen(!exportOpen)}
              className="px-4 py-2.5 border border-outline-variant/20 text-on-surface font-medium rounded-lg flex items-center gap-2 hover:border-primary/40 hover:text-primary active:scale-95 transition-all text-sm"
            >
              <Icon name="upload_file" className="text-base" />
              Export
            </button>
            {exportOpen ? (
              <div className="absolute bottom-full left-0 mb-2 w-48 rounded-xl border border-outline-variant/10 bg-surface-lowest shadow-2xl overflow-hidden">
                <a
                  href={count > 0 ? undefined : "#"}
                  onClick={onExport}
                  className="flex items-center gap-3 px-4 py-3 text-sm text-on-surface hover:bg-surface transition-colors"
                >
                  <Icon name="upload_file" className="text-sm text-primary" />
                  CSV
                </a>
                <div className="flex items-center gap-3 px-4 py-3 text-sm text-on-surface-variant/50 cursor-not-allowed">
                  <Icon name="upload_file" className="text-sm" />
                  Apollo Format
                  <span className="ml-auto text-[10px] uppercase tracking-wider text-tertiary">Soon</span>
                </div>
                <div className="flex items-center gap-3 px-4 py-3 text-sm text-on-surface-variant/50 cursor-not-allowed">
                  <Icon name="upload_file" className="text-sm" />
                  HubSpot
                  <span className="ml-auto text-[10px] uppercase tracking-wider text-tertiary">Soon</span>
                </div>
                <div className="flex items-center gap-3 px-4 py-3 text-sm text-on-surface-variant/50 cursor-not-allowed">
                  <Icon name="upload_file" className="text-sm" />
                  Salesforce
                  <span className="ml-auto text-[10px] uppercase tracking-wider text-tertiary">Soon</span>
                </div>
              </div>
            ) : null}
          </div>

          <button
            onClick={onCompare}
            className="px-4 py-2.5 border border-outline-variant/20 text-on-surface font-medium rounded-lg flex items-center gap-2 hover:border-primary/40 hover:text-primary active:scale-95 transition-all text-sm"
          >
            <Icon name="insights" className="text-base" />
            Compare
          </button>
        </div>

        <div className="h-8 w-px bg-outline-variant/20" />

        <button
          onClick={onClear}
          className="px-3 py-2.5 text-on-surface-variant font-medium hover:text-error transition-colors flex items-center gap-1 text-sm"
        >
          <Icon name="close" className="text-base" />
          Clear
        </button>
      </div>
    </div>
  );
}
