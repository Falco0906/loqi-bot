"use client";

import { memo } from "react";
import Icon from "../shared/Icon";
import type { QuickReplyOption } from "../../lib/conversationMachine";

type Props = {
  options: QuickReplyOption[];
  onSelect: (option: QuickReplyOption) => void;
};

function QuickReplies({ options, onSelect }: Props) {
  if (options.length === 0) return null;

  return (
    <div className="px-4 pb-3 space-y-2">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          onClick={() => onSelect(o)}
          className="w-full text-left rounded-xl border border-outline-variant/15 bg-surface-container-low px-3.5 py-2.5 hover:border-primary/30 hover:bg-surface-high/40 active:scale-[0.98] transition-all group"
        >
          <span className="flex items-center justify-between gap-2">
            <span className="text-body-sm text-on-surface font-medium">{o.label}</span>
            <Icon
              name="chevron_right"
              className="text-on-surface-variant/40 group-hover:text-primary text-sm transition-colors"
            />
          </span>
          {o.hint && (
            <span className="block text-label-sm text-on-surface-variant/50 mt-0.5">
              {o.hint}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

export default memo(QuickReplies);
