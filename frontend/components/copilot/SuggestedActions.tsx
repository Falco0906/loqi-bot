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
    <div className="flex flex-wrap gap-2 px-4 pb-3">
      {actions.map((a, i) => (
        <button
          key={`${a.label}-${i}`}
          onClick={() => onExecute(a)}
          className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/5 px-3 py-1.5 text-label-sm text-primary font-medium hover:bg-primary/10 transition-all"
        >
          {a.type === "navigate" && <Icon name="chevron_right" className="text-sm" />}
          {a.label}
        </button>
      ))}
    </div>
  );
}
