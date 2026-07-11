"use client";

import { useState } from "react";
import { saveCampaign } from "../../lib/api";
import Icon from "../shared/Icon";

type Props = {
  sessionToken: string;
  selectedCount: number;
  searchQuery: string;
  leads: unknown[];
  onClose: () => void;
  onSaved: (name: string) => void;
};

export default function SaveCampaignModal({ sessionToken, selectedCount, searchQuery, leads, onClose, onSaved }: Props) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    if (!name.trim() || saving) return;
    setSaving(true);
    try {
      await saveCampaign(sessionToken, name.trim(), searchQuery, selectedCount, undefined, undefined, leads);
      onSaved(name.trim());
    } catch {
      /* ignore */
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-surface-lowest border border-outline-variant/10 rounded-2xl w-[420px] p-6 shadow-2xl">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-headline-md font-bold text-on-surface">Save Campaign</h2>
          <button onClick={onClose} className="text-on-surface-variant/60 hover:text-on-surface transition-colors">
            <Icon name="close" />
          </button>
        </div>

        <p className="text-sm text-on-surface-variant mb-4">
          Save {selectedCount} selected {selectedCount === 1 ? "lead" : "leads"} as a campaign for future outreach.
        </p>

        <label className="block text-label-md text-on-surface-variant uppercase tracking-wider mb-1.5">
          Campaign Name
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Restaurant Expansion"
          className="w-full rounded-xl border border-outline-variant/20 bg-surface-lowest px-4 py-3 text-body-md text-on-surface outline-none placeholder:text-on-surface-variant/40 focus:border-primary/50 mb-1"
          onKeyDown={(e) => { if (e.key === "Enter") handleSave(); }}
        />
        <p className="text-xs text-on-surface-variant/50 mb-4">
          {selectedCount} {selectedCount === 1 ? "lead" : "leads"} will be saved
        </p>

        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 px-5 py-2.5 border border-outline-variant/20 text-on-surface font-medium rounded-xl hover:bg-surface transition-all text-sm"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!name.trim() || saving}
            className="flex-1 px-5 py-2.5 bg-primary text-on-primary font-bold rounded-xl hover:brightness-110 transition-all text-sm disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save Campaign"}
          </button>
        </div>
      </div>
    </div>
  );
}
