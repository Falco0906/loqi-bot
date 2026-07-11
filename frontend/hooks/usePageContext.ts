"use client";

import { useEffect } from "react";
import { useCopilot } from "../contexts/CopilotContext";

export function usePageContext(
  page: string,
  data: Record<string, unknown>,
) {
  const { setPageContext } = useCopilot();

  useEffect(() => {
    setPageContext({ page, data });
    return () => setPageContext(null);
  }, [page, data, setPageContext]);
}
