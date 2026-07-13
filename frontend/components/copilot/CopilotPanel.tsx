"use client";

import { useEffect } from "react";
import { useCopilot } from "../../contexts/CopilotContext";
import ConversationHistory from "./ConversationHistory";
import CopilotComposer from "./CopilotComposer";

export default function CopilotPanel() {
  const { open, setOpen, messages, sending, send, executeAction, clear } = useCopilot();

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen(!open);
      }
      if (e.key === "Escape" && open) {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, setOpen]);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-40 w-12 h-12 rounded-full bg-primary text-on-primary shadow-lg shadow-primary/20 flex items-center justify-center hover:brightness-110 hover:shadow-primary/30 hover:scale-105 active:scale-95 transition-all duration-150"
        title="Open Loqi OS (⌘K)"
        aria-label="Open Loqi OS"
      >
        <svg viewBox="0 0 24 24" className="w-5 h-5" fill="currentColor">
          <path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 14H4V6h16v12zM6 10h2v2H6v-2zm0 4h6v2H6v-2zm8-4h4v2h-4v-2zm0 4h4v2h-4v-2zM6 14h2v2H6v-2zm8-4h4v2h-4v-2z" />
        </svg>
      </button>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-end pt-16 pb-0 pr-4 bg-black/20 backdrop-blur-sm animate-fade-in"
      onClick={() => setOpen(false)}
      role="dialog"
      aria-modal="true"
      aria-label="Loqi OS"
    >
      <div
        className="w-full max-w-sm h-[calc(100vh-5rem)] rounded-2xl border border-outline-variant/20 bg-surface-lowest shadow-2xl flex flex-col overflow-hidden animate-slide-up"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-outline-variant/10 shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-primary/15 flex items-center justify-center">
              <svg viewBox="0 0 24 24" className="w-4 h-4 text-primary" fill="currentColor">
                <path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 14H4V6h16v12z" />
              </svg>
            </div>
            <span className="text-body-md text-on-surface font-bold">Loqi OS</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={clear}
              className="p-1.5 rounded-lg text-on-surface-variant/50 hover:text-on-surface hover:bg-surface-high/60 transition-all duration-150 active:scale-95"
              title="Clear conversation"
              aria-label="Clear conversation"
            >
              <svg viewBox="0 0 24 24" className="w-4 h-4" fill="currentColor">
                <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12 19 6.41z" />
              </svg>
            </button>
            <button
              onClick={() => setOpen(false)}
              className="p-1.5 rounded-lg text-on-surface-variant/50 hover:text-on-surface hover:bg-surface-high/60 transition-all duration-150 active:scale-95"
              title="Close (ESC)"
              aria-label="Close Loqi OS"
            >
              <svg viewBox="0 0 24 24" className="w-4 h-4" fill="currentColor">
                <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12 19 6.41z" />
              </svg>
            </button>
          </div>
        </div>

        <ConversationHistory
          messages={messages}
          sending={sending}
          onExecuteAction={executeAction}
        />

        <div className="shrink-0">
          <div className="px-4 pt-1 pb-0.5">
            <div className="flex items-center gap-2 text-label-sm text-on-surface-variant/40">
              <span className="w-1.5 h-1.5 rounded-full bg-success/60" />
              Loqi OS
            </div>
          </div>
          <CopilotComposer onSend={send} disabled={sending} />
        </div>
      </div>
    </div>
  );
}
