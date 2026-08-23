"use client";

import { useCallback, useState } from "react";
import { useCopilotActions } from "../contexts/CopilotContext";

/**
 * Shared Tell Loqi wiring: open Copilot and route the user's instruction
 * through the deterministic conversation state machine (Phase 11D).
 * Used by primary workspaces that share the Narrative → Workspace → Input model.
 * Consumes only the actions context — workspace pages never re-render
 * on sidebar state changes.
 */
export function useTellLoqi(page: string, pageData: Record<string, unknown> = {}): { text: string; setText: (t: string) => void; sending: boolean; submit: (override?: string) => Promise<boolean> } {
  const { startTask, setOpen, setPageContext } = useCopilotActions();
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);

  const submit = useCallback(
    async (override?: string) => {
      const message = (override ?? text).trim();
      if (!message || sending) return false;
      setSending(true);
      let handled = false;
      try {
        console.info(`[discovery] submit page=${page} chars=${message.length}`);
        setPageContext({ page, data: pageData });
        setOpen(true);
        handled = startTask(message);
        // PR-4 FIX: a false return means the request was DROPPED (Copilot
        // busy / unclassified on non-Discovery pages). Never silently no-op.
        if (!handled) {
          console.warn("[discovery] submit dropped by copilot (busy/unclassified)");
        }
      } finally {
        setSending(false);
      }
      return handled;
    },
    [text, sending, page, pageData, startTask, setOpen, setPageContext],
  );

  return { text, setText, sending, submit };
}
