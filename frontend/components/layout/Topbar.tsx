"use client";

import Badge from "../shared/Badge";
import Icon from "../shared/Icon";

type Props = {
  title?: string;
};

export default function Topbar({ title }: Props) {
  return (
    <header className="fixed right-0 top-0 z-20 flex h-16 items-center justify-between border-b border-outline-variant/10 bg-charcoal/80 px-6 backdrop-blur-xl"
      style={{ left: "256px" }}
    >
      <div className="flex items-center gap-3">
        {title ? (
          <h1 className="text-headline-md text-on-surface">{title}</h1>
        ) : null}
        <Badge variant="primary">2 active campaigns</Badge>
        <Badge variant="secondary">New leads detected</Badge>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-on-surface-variant/50 transition-all duration-150 hover:bg-surface-high/80 hover:text-on-surface active:scale-95"
          aria-label="Notifications"
        >
          <Icon name="notifications" className="text-xl" />
        </button>
        <button
          type="button"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-on-surface-variant/50 transition-all duration-150 hover:bg-surface-high/80 hover:text-on-surface active:scale-95"
          aria-label="AI assistant status"
        >
          <Icon name="smart_toy" className="text-xl" />
        </button>
        <div className="flex h-8 w-8 items-center justify-center rounded-full border border-outline-variant/20 bg-surface-high text-xs font-semibold text-on-surface select-none">
          L
        </div>
      </div>
    </header>
  );
}
