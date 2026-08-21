"use client";

import { useEffect, type RefObject } from "react";

type HighlightCtor = new (...ranges: Range[]) => unknown;

/**
 * Highlights every occurrence of `query` inside `containerRef` using the
 * CSS Custom Highlight API — no DOM mutation, works across all text nodes.
 * Used for content/report pages (Mission Control, Knowledge, etc.).
 */
export function useTextHighlight(
  query: string,
  containerRef: RefObject<HTMLElement | null>,
  active: boolean
) {
  useEffect(() => {
    const root = containerRef.current;
    const css = typeof CSS !== "undefined" ? (CSS as unknown as { highlights?: Map<string, unknown> }) : null;
    const highlights = css?.highlights;
    const HighlightCtor = (typeof window !== "undefined" ? window : undefined) as unknown as { Highlight?: HighlightCtor };
    if (!root || !highlights || !HighlightCtor.Highlight) return;

    highlights.delete("loqi-search");
    const q = query.trim().toLowerCase();
    if (!active || q.length < 2) return;

    const ranges: Range[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      const parent = node.parentElement;
      if (parent && !parent.closest("input, textarea, [contenteditable]")) {
        const text = node.nodeValue ?? "";
        if (text) {
          const lower = text.toLowerCase();
          let idx = lower.indexOf(q);
          while (idx !== -1) {
            const range = new Range();
            range.setStart(node, idx);
            range.setEnd(node, idx + q.length);
            ranges.push(range);
            idx = lower.indexOf(q, idx + q.length);
          }
        }
      }
      node = walker.nextNode();
    }

    if (ranges.length > 0) {
      highlights.set("loqi-search", new HighlightCtor.Highlight(...ranges));
    }
    return () => {
      highlights.delete("loqi-search");
    };
  }, [query, active, containerRef]);
}
