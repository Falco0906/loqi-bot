"use client";

import { useEffect } from "react";

/**
 * Sync the browser-tab title with the current page. Purely client-side —
 * no requests, no latency. Restores the app default on unmount so nested
 * navigations never leave a stale page name behind.
 */
export function usePageTitle(title: string) {
  useEffect(() => {
    const previous = document.title;
    document.title = title ? `${title} — Loqi` : "Loqi";
    return () => {
      document.title = previous;
    };
  }, [title]);
}
