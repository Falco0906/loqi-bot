"use client";

import Badge from "../shared/Badge";
import Icon from "../shared/Icon";

type Props = {
  title?: string;
};

export default function Topbar({ title }: Props) {
  return (
    <header className="fixed right-0 top-0 z-20 flex h-16 items-center justify-between border-b border-outline-variant/20 bg-charcoal/80 px-6 backdrop-blur-xl"
      style={{ left: "256px" }}
    >
      <div className="flex items-center gap-3">
        {title ? (
          <h1 className="text-headline-md text-on-surface">{title}</h1>
        ) : null}
        <Badge variant="primary">Monitoring 4 campaigns</Badge>
        <Badge variant="secondary">Detecting hiring signals</Badge>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-on-surface-variant/60 transition hover:bg-surface-high hover:text-on-surface"
        >
          <Icon name="notifications" className="text-xl" />
        </button>
        <button
          type="button"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-on-surface-variant/60 transition hover:bg-surface-high hover:text-on-surface"
        >
          <Icon name="smart_toy" className="text-xl" />
        </button>
        <div className="flex h-8 w-8 items-center justify-center rounded-full border border-outline-variant/30 bg-surface-high text-xs font-semibold text-on-surface">
          L
        </div>
      </div>
    </header>
  );
}
