"use client";

import Icon from "../shared/Icon";
import WorkspaceSwitcher from "./WorkspaceSwitcher";

type Props = {
  title?: string;
};

export default function Topbar({ title }: Props) {
  return (
    <header className="fixed right-0 top-0 z-20 flex h-16 items-center justify-between border-b border-outline-variant/10 bg-charcoal/80 px-6 backdrop-blur-xl"
      style={{ left: "256px" }}
    >
      <div className="flex items-center gap-4">
        <WorkspaceSwitcher />
        {title && (
          <>
            <span className="text-outline-variant">/</span>
            <h1 className="text-headline-md text-on-surface">{title}</h1>
          </>
        )}
      </div>

      <div className="flex items-center gap-2">
        {/* User Menu Placeholder */}
        <button className="flex h-8 w-8 items-center justify-center rounded-full border border-outline-variant/20 bg-surface-high text-xs font-semibold text-on-surface select-none">
          L
        </button>
      </div>
    </header>
  );
}
