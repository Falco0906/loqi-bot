"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { useCopilot } from "../../contexts/CopilotContext";
import { useWorkspaceSearch } from "../../contexts/SearchContext";
import { usePageTitle } from "../../hooks/usePageTitle";

export const pageConfig: Record<string, { title: string; searchPlaceholder: string }> = {
  "/mission-control": { title: "Briefing", searchPlaceholder: "Search briefings..." },
  "/discovery": { title: "Discovery", searchPlaceholder: "Research a different market..." },
  "/campaigns": { title: "Campaigns", searchPlaceholder: "Search campaigns..." },
  "/inbox": { title: "Inbox", searchPlaceholder: "Search inbox..." },
  "/knowledge": { title: "Knowledge", searchPlaceholder: "Search knowledge..." },
  "/strategic-update": { title: "Strategic Update", searchPlaceholder: "Search..." },
  "/settings": { title: "Settings", searchPlaceholder: "Search..." },
  "/support": { title: "Support", searchPlaceholder: "Search..." },
  "/draft": { title: "Review", searchPlaceholder: "Search..." },
  "/copilot": { title: "Copilot", searchPlaceholder: "Ask Copilot..." },
};

export default function Topbar() {
  const pathname = usePathname() ?? "";
  const config = pageConfig[pathname] ?? { title: "", searchPlaceholder: "Search..." };
  const { open, setOpen } = useCopilot();
  const { query, setQuery } = useWorkspaceSearch();
  const copilotAvailable = pathname !== "/draft";

  // PR: tab title follows the current page ("Campaigns — Loqi"). Uses the
  // already-computed route config — no fetches, no added latency.
  usePageTitle(config.title);

  return (
    <header className="shrink-0 grid h-16 grid-cols-[minmax(0,1fr)_minmax(220px,420px)_minmax(0,1fr)] items-center gap-6 border-b border-outline-variant/5 bg-surface-lowest/50 px-6 backdrop-blur-md">
      <h1 className="min-w-0 truncate font-serif text-[24px] text-on-surface tracking-tighter">{config.title}</h1>

      <label className="flex h-9 w-full items-center gap-2 rounded-lg border border-outline-variant/15 bg-surface-lowest/55 px-3 text-on-surface-variant/60 transition-colors focus-within:border-primary/30">
        <span className="material-symbols-outlined shrink-0 text-[18px]">search</span>
        <input
          type="text"
          aria-label="Search workspace"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={config.searchPlaceholder}
          className="min-w-0 flex-1 bg-transparent text-sm text-on-surface outline-none placeholder:text-on-surface-variant/45"
        />
        {query && (
          <button
            type="button"
            onClick={() => setQuery("")}
            aria-label="Clear workspace search"
            className="shrink-0 text-on-surface-variant/45 transition-colors hover:text-on-surface"
          >
            <span className="material-symbols-outlined text-[16px]">close</span>
          </button>
        )}
      </label>

      <div className="flex items-center justify-end gap-3">
        <button
          className="p-2 text-on-surface-variant hover:text-primary transition-colors"
          aria-label="Notifications"
        >
          <span className="material-symbols-outlined text-[22px]">notifications</span>
        </button>
        {copilotAvailable && (
          <button
            onClick={() => setOpen(!open)}
            className={`h-9 min-w-9 grid place-items-center rounded-full transition-all duration-150 active:scale-95 ${
              open
                ? "border border-outline-variant/30 text-on-surface-variant hover:text-error hover:border-error/40"
                : "bg-primary text-on-primary shadow-md shadow-primary/25 hover:brightness-110 hover:shadow-primary/40"
            }`}
            title={open ? "Close Ask Loqi (ESC)" : "Open Ask Loqi"}
            aria-label={open ? "Close Ask Loqi" : "Open Ask Loqi"}
          >
            <span className="material-symbols-outlined text-[20px]">{open ? "close" : "smart_toy"}</span>
          </button>
        )}
      </div>
    </header>
  );
}
