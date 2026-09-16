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
type TimerHandle = ReturnType<typeof setTimeout>;

type PollingLoopOptions = {
  jobId: string;
  getJob: (jobId: string) => Promise<JobResponse>;
  getJobResults: (jobId: string) => Promise<{ ok: boolean; leads: Record<string, unknown>[] }>;
  onJob: (job: JobResponse) => void;
  onCompleted: (leads: Record<string, unknown>[]) => void;
  onTerminal: () => void;
  setTimeoutFn?: (callback: () => void, delay: number) => TimerHandle;
  clearTimeoutFn?: (handle: TimerHandle) => void;
};

/** Completion-scheduled polling prevents overlapping status requests. */
export function createJobPollingLoop({
  jobId,
  getJob: fetchJob,
  getJobResults: fetchResults,
  onJob,
  onCompleted,
  onTerminal,
  setTimeoutFn = setTimeout,
  clearTimeoutFn = clearTimeout,
}: PollingLoopOptions): () => void {
  let active = true;
  let terminal = false;
  let inFlight = false;
  let attempt = 0;
  let timeout: TimerHandle | null = null;

  const scheduleNext = () => {
    if (!active || terminal) return;
    const delay = INTERVALS[Math.min(attempt, INTERVALS.length - 1)];
    timeout = setTimeoutFn(() => {
      timeout = null;
      void poll();
    }, delay);
  };

  const poll = async () => {
    if (!active || terminal || inFlight) return;
    inFlight = true;
    try {
      const job = await fetchJob(jobId);
      if (!active) return;

      attempt = 0;
      onJob(job);

      if (job.status === "completed") {
        terminal = true;
        try {
          const results = await fetchResults(jobId);
          if (active) onCompleted((results.leads || []) as Record<string, unknown>[]);
        } catch {
          // Preserve completed-without-results behavior while stopping polls.
        }
      } else if (job.status === "failed" || job.status === "cancelled") {
        terminal = true;
        onTerminal();
      }
    } catch {
      if (active) attempt += 1;
    } finally {
      inFlight = false;
      if (active && !terminal) scheduleNext();
    }
  };

  void poll();
  return () => {
    active = false;
    if (timeout !== null) clearTimeoutFn(timeout);
  };
}

export function useJobPolling(jobId: string | null) {
  const [state, setState] = useState<JobPollState>({
    status: "idle",
    stage: "",
    progress: 0,
    error: null,
    leads: [],
    done: false,
  });
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    cleanupRef.current?.();
    if (!jobId) return;

    cleanupRef.current = createJobPollingLoop({
      jobId,
      getJob,
      getJobResults,
      onJob: (job) => {
        setState((prev) => ({
          ...prev,
          status: job.status,
          stage: job.stage,
          progress: job.progress,
          error: job.error_message,
        }));
      },
      onCompleted: (leads) => {
        setState((prev) => ({
          ...prev,
          status: "completed",
          leads,
          done: true,
        }));
      },
      onTerminal: () => {
        setState((prev) => ({ ...prev, done: true }));
      },
    });

    return () => {
      cleanupRef.current?.();
      cleanupRef.current = null;
    };
  }, [jobId]);

  return state;
}
