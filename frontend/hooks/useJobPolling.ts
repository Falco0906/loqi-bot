"use client";

import { useEffect, useRef, useState } from "react";
import { getJob, getJobResults, type JobResponse } from "../lib/api";

export type JobPollState = {
  status: JobResponse["status"] | "idle";
  stage: string;
  progress: number;
  error: string | null;
  leads: Record<string, unknown>[];
  done: boolean;
};

const INTERVALS = [1000, 2000, 4000, 6000, 8000];

export function useJobPolling(jobId: string | null) {
  const [state, setState] = useState<JobPollState>({
    status: "idle",
    stage: "",
    progress: 0,
    error: null,
    leads: [],
    done: false,
  });
  const attemptRef = useRef(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!jobId) return;

    attemptRef.current = 0;

    const poll = async () => {
      try {
        const job = await getJob(jobId);
        setState((prev) => ({
          ...prev,
          status: job.status,
          stage: job.stage,
          progress: job.progress,
          error: job.error_message,
        }));

        if (job.status === "completed") {
          if (intervalRef.current) clearInterval(intervalRef.current);
          const results = await getJobResults(jobId);
          setState((prev) => ({
            ...prev,
            status: "completed",
            leads: (results.leads || []) as Record<string, unknown>[],
            done: true,
          }));
        } else if (job.status === "failed" || job.status === "cancelled") {
          if (intervalRef.current) clearInterval(intervalRef.current);
          setState((prev) => ({ ...prev, done: true }));
        }
      } catch {
        attemptRef.current += 1;
      }
    };

    poll();
    const idx = Math.min(attemptRef.current, INTERVALS.length - 1);
    intervalRef.current = setInterval(poll, INTERVALS[idx]);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [jobId]);

  return state;
}
