"use client";

import { useEffect, useState, useCallback } from "react";
import { checkHealth } from "../lib/api";

export function useBackendHealth() {
  const [healthy, setHealthy] = useState<boolean | null>(null);

  const retry = useCallback(async () => {
    const result = await checkHealth();
    setHealthy(result.ok);
  }, []);

  useEffect(() => {
    retry();
  }, [retry]);

  return { healthy, retry };
}
