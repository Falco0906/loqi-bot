"use client";

import { usePathname } from "next/navigation";

const pageConfig: Record<string, { title: string; searchPlaceholder: string }> = {
  "/mission-control": { title: "Briefing", searchPlaceholder: "Search briefings..." },
  "/discovery": { title: "Discovery", searchPlaceholder: "Research a different market..." },
  "/campaigns": { title: "Campaigns", searchPlaceholder: "Search campaigns..." },
  "/inbox": { title: "Inbox", searchPlaceholder: "Search inbox..." },
  "/knowledge": { title: "Knowledge", searchPlaceholder: "Search knowledge..." },
  "/strategic-update": { title: "Strategic Update", searchPlaceholder: "Search..." },
  "/settings": { title: "Settings", searchPlaceholder: "Search..." },
  "/support": { title: "Support", searchPlaceholder: "Search..." },
  "/draft": { title: "Draft Review", searchPlaceholder: "Search..." },
};

export default function Topbar() {
  const pathname = usePathname() ?? "";
  const config = pageConfig[pathname] ?? { title: "", searchPlaceholder: "Search..." };

  return (
    <header className="shrink-0 flex h-16 items-center justify-between border-b border-outline-variant/10 bg-surface-lowest/50 px-6 backdrop-blur-md">
      <h1 className="font-serif text-[24px] text-on-surface tracking-tighter">{config.title}</h1>

      <div className="flex items-center gap-4">
        <div className="relative w-64">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-[18px]">
            search
          </span>
          <input
            className="w-full pl-10 pr-4 py-2 bg-surface-container border-none rounded-full text-label-sm text-on-surface placeholder:text-on-surface-variant/40 focus:ring-1 focus:ring-primary/20 transition-all"
            placeholder={config.searchPlaceholder}
            type="text"
            aria-label="Search"
          />
        </div>
        <button
          className="p-2 text-on-surface-variant hover:text-primary transition-colors"
          aria-label="Notifications"
        >
          <span className="material-symbols-outlined text-[22px]">notifications</span>
        </button>
      </div>
    </header>
  );
}
