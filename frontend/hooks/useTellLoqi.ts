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
export function useTellLoqi(page: string, pageData: Record<string, unknown> = {}) {
  const { startTask, setOpen, setPageContext } = useCopilotActions();
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);

  const submit = useCallback(
    async (override?: string) => {
      const message = (override ?? text).trim();
      if (!message || sending) return;
      setSending(true);
      try {
        setPageContext({ page, data: pageData });
        setOpen(true);
        startTask(message);
        setText("");
      } finally {
        setSending(false);
      }
    },
    [text, sending, page, pageData, startTask, setOpen, setPageContext],
  );

  return { text, setText, sending, submit };
}
