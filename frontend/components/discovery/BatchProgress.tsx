"use client";

import { useEffect, useState, useCallback } from "react";
import { batchStatus } from "../../lib/api";
import Icon from "../shared/Icon";

type DraftEntry = {
  id: string;
  lead: { name?: string; first_name?: string; last_name?: string };
  text: string;
  status: string;
};

type Props = {
  sessionToken: string;
  batchId: string;
  total: number;
  onComplete: (drafts: DraftEntry[]) => void;
  onError: (err: string) => void;
};

type LeadProgress = {
  name: string;
  state: "waiting" | "processing" | "done" | "error";
};

export default function BatchProgress({ sessionToken, batchId, total, onComplete, onError }: Props) {
  const [leads, setLeads] = useState<LeadProgress[]>(() =>
    Array.from({ length: total }, (_, i) => ({ name: `Lead ${i + 1}`, state: "waiting" as const })),
  );
  const [completed, setCompleted] = useState(0);
  const [done, setDone] = useState(false);

  const poll = useCallback(async () => {
    try {
      const res = await batchStatus(sessionToken, batchId);
      if (!res.ok) return;

      setCompleted(res.completed);

      const newLeads = [...leads];
      for (let i = 0; i < total; i++) {
        if (i < res.completed) {
          const draft = res.drafts[i];
          const dl = draft?.lead as { name?: string; first_name?: string; last_name?: string } | undefined;
          newLeads[i] = {
            name: dl?.name || dl?.first_name || `Lead ${i + 1}`,
            state: "done",
          };
        } else if (i === res.current_index && res.status === "processing") {
          newLeads[i] = {
            name: res.current_name || `Lead ${i + 1}`,
            state: "processing",
          };
        }
      }
      setLeads(newLeads);

      if (res.status === "completed") {
        setDone(true);
        onComplete(res.drafts as DraftEntry[]);
      }
    } catch (err) {
      onError(err instanceof Error ? err.message : "Batch failed");
    }
  }, [sessionToken, batchId, total, leads, onComplete, onError]);

  useEffect(() => {
    if (done) return;
    const interval = setInterval(poll, 800);
    return () => clearInterval(interval);
  }, [poll, done]);

  return (
    <div className="bg-surface-lowest border border-outline-variant/10 rounded-xl p-6 space-y-4">
      <div className="flex items-center gap-3">
        <Icon name="auto_awesome" className="text-primary animate-pulse" />
        <div>
          <p className="font-bold text-on-surface">Preparing drafts...</p>
          <p className="text-sm text-on-surface-variant">Processing leads in sequence</p>
        </div>
      </div>

      <div className="space-y-1.5 mt-3">
        {leads.map((lead, i) => (
          <div key={i} className="flex items-center gap-3 text-sm">
            {lead.state === "done" ? (
              <span className="w-4 h-4 rounded-full bg-secondary/20 flex items-center justify-center">
                <Icon name="chevron_right" className="text-secondary text-xs" />
              </span>
            ) : lead.state === "processing" ? (
              <span className="w-4 h-4 rounded-full border-2 border-primary border-t-transparent animate-spin" />
            ) : (
              <span className="w-4 h-4 rounded-full border border-outline-variant/20" />
            )}
            <span className={lead.state === "waiting" ? "text-on-surface-variant/50" : "text-on-surface"}>
              {lead.name}
            </span>
            {lead.state === "done" ? (
              <span className="text-secondary text-xs ml-auto">Done</span>
            ) : lead.state === "processing" ? (
              <span className="text-primary text-xs ml-auto animate-pulse">Generating...</span>
            ) : (
              <span className="text-on-surface-variant/30 text-xs ml-auto">Waiting</span>
            )}
          </div>
        ))}
      </div>

      <div className="mt-2">
        <div className="flex justify-between text-sm mb-1.5">
          <span className="text-on-surface-variant">Progress</span>
          <span className="font-bold text-primary">{completed} / {total} Complete</span>
        </div>
        <div className="h-2 bg-surface rounded-full overflow-hidden">
          <div
            className="h-full bg-primary rounded-full transition-all duration-500"
            style={{ width: `${total > 0 ? (completed / total) * 100 : 0}%` }}
          />
        </div>
      </div>
    </div>
  );
}
