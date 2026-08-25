"use client";

import { memo } from "react";
import Icon from "../shared/Icon";
import type { QuickReplyOption } from "../../lib/conversationMachine";

type Props = {
  options: QuickReplyOption[];
  onSelect: (option: QuickReplyOption) => void;
  variant?: "sidebar" | "page";
};

function QuickReplies({ options, onSelect, variant = "sidebar" }: Props) {
  if (options.length === 0) return null;

  return (
    <div className={variant === "page" ? "mx-auto grid w-full max-w-3xl grid-cols-1 gap-2 px-6 pb-2 sm:grid-cols-2 md:px-10" : "space-y-2 px-4 pb-3"}>
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          onClick={() => onSelect(o)}
          className={`${variant === "page" ? "rounded-xl px-4 py-3" : "rounded-xl px-3.5 py-2.5"} w-full text-left border border-on-surface/5 bg-surface-container-low/45 hover:border-on-surface/10 hover:bg-surface-high/40 active:scale-[0.98] transition-all group`}
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
