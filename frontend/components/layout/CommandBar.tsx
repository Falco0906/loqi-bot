"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import Icon from "../shared/Icon";

const QUICK_ACTIONS = [
  { label: "Go to Discovery", href: "/discovery", icon: "explore" as const },
  { label: "Go to Campaigns", href: "/campaigns", icon: "campaign" as const },
  { label: "Go to Draft Review", href: "/draft", icon: "edit_note" as const },
  { label: "Go to Campaign Intelligence", href: "/campaign-intelligence", icon: "insights" as const },
  { label: "Go to Mission Control", href: "/mission-control", icon: "dashboard" as const },
];

export default function CommandBar() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const filtered = QUICK_ACTIONS.filter(
    (a) => a.label.toLowerCase().includes(query.toLowerCase()),
  );

  const goTo = useCallback(
    (href: string) => {
      setOpen(false);
      setQuery("");
      router.push(href);
    },
    [router],
  );

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
      if (e.key === "Escape") {
        setOpen(false);
        setQuery("");
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus();
      setSelectedIndex(0);
    }
  }, [open]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % filtered.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev - 1 + filtered.length) % filtered.length);
    } else if (e.key === "Enter" && filtered[selectedIndex]) {
      goTo(filtered[selectedIndex].href);
    } else if (e.key === "Escape") {
      setOpen(false);
      setQuery("");
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-40 w-12 h-12 rounded-full bg-primary text-on-primary shadow-lg flex items-center justify-center hover:brightness-110 active:scale-95 transition-all"
        title="Command palette (⌘K)"
        aria-label="Open command palette"
      >
        <Icon name="terminal" className="text-lg" />
      </button>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh] bg-black/40 backdrop-blur-sm animate-fade-in"
      onClick={() => { setOpen(false); setQuery(""); }}
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      <div
        className="w-full max-w-xl rounded-2xl border border-outline-variant/20 bg-surface-lowest shadow-2xl overflow-hidden animate-slide-up"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-5 py-4 border-b border-outline-variant/10">
          <Icon name="search" className="text-lg text-on-surface-variant/60" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setSelectedIndex(0); }}
            onKeyDown={handleKeyDown}
            placeholder="Search pages and actions..."
            className="flex-1 border-none bg-transparent text-body-md text-on-surface outline-none placeholder:text-on-surface-variant/40"
            aria-label="Search pages and actions"
          />
          <kbd className="hidden sm:inline-flex rounded-md border border-outline-variant/20 bg-surface-high px-2 py-0.5 text-mono-sm text-on-surface-variant/60 shrink-0">
            ESC
          </kbd>
        </div>
        {filtered.length > 0 ? (
          <ul className="py-2 max-h-64 overflow-y-auto" role="listbox" aria-label="Commands">
            {filtered.map((action, i) => (
              <li
                key={action.href}
                role="option"
                aria-selected={i === selectedIndex}
              >
                <button
                  onClick={() => goTo(action.href)}
                  onMouseEnter={() => setSelectedIndex(i)}
                  className={`w-full flex items-center gap-3 px-5 py-3 text-left text-body-md transition-all duration-100 ${
                    i === selectedIndex
                      ? "bg-primary/10 text-primary"
                      : "text-on-surface/80 hover:bg-surface-high/50"
                  }`}
                >
                  <Icon name={action.icon} className="text-lg shrink-0" />
                  {action.label}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <div className="px-5 py-8 text-center text-label-sm text-on-surface-variant/40">
            No results for &ldquo;{query}&rdquo;
          </div>
        )}
      </div>
    </div>
  );
}
