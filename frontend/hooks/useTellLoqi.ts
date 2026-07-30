"use client";

import { useCallback, useState } from "react";
import { useCopilot } from "../contexts/CopilotContext";

/**
 * Shared Tell Loqi wiring: open Copilot and send the user's instruction.
 * Used by primary workspaces that share the Narrative → Workspace → Input model.
 */
export function useTellLoqi(page: string, pageData: Record<string, unknown> = {}) {
  const { send, setOpen, setPageContext } = useCopilot();
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
        await send(message);
        setText("");
      } finally {
        setSending(false);
      }
    },
    [text, sending, page, pageData, send, setOpen, setPageContext],
  );

  return { text, setText, sending, submit };
}
