"use client";

import { useEffect, useRef } from "react";
import { useCopilot } from "../contexts/CopilotContext";
import type { ActionType, ActionHandler } from "../lib/actionRegistry";

export function useActionHandlers(
  handlers: Record<string, ActionHandler>,
) {
  const { registerHandler, unregisterHandler } = useCopilot();
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    const keys = Object.keys(handlersRef.current) as ActionType[];
    for (const key of keys) {
      registerHandler(key, handlersRef.current[key]);
    }
    return () => {
      for (const key of keys) {
        unregisterHandler(key);
      }
    };
  }, [registerHandler, unregisterHandler]);
}
