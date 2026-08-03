"use client";

import { useEffect, useRef } from "react";
import { useCopilotActions } from "../contexts/CopilotContext";

export function usePageContext(
  page: string,
  data: Record<string, unknown>,
) {
  const { setPageContext } = useCopilotActions();
  const prevRef = useRef<string>("");

  useEffect(() => {
    const key = JSON.stringify({ page, data });
    if (key === prevRef.current) return;
    prevRef.current = key;
    setPageContext({ page, data });
    return () => {
      setPageContext(null);
    };
  }, [page, data, setPageContext]);
}
