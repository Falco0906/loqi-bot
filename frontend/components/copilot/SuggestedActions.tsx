"use client";

import Icon from "../shared/Icon";
import type { CopilotAction } from "../../lib/actionRegistry";

type Props = {
  actions: CopilotAction[];
  onExecute: (action: CopilotAction) => void;
};

export default function SuggestedActions({ actions, onExecute }: Props) {
  if (actions.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5 mt-1">
      {actions.map((a, i) => (
        <button
          key={`${a.label}-${i}`}
          onClick={() => onExecute(a)}
          className="inline-flex items-center gap-1 rounded-lg border border-primary/15 bg-primary/5 px-2.5 py-1 text-[11px] font-semibold text-primary hover:bg-primary/12 hover:border-primary/25 active:scale-95 transition-all"
        >
          <Icon name={a.type === "navigate" ? "open_in_new" : "play_arrow"} className="text-[10px]" />
          {a.label}
        </button>
      ))}
    </div>
  );
}
