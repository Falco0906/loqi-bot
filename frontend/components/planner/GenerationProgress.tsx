"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getCampaignGenerationStatus } from "../../lib/api";
import Icon from "../shared/Icon";

type Props = {
  sessionToken: string;
  campaignId: string;
  campaignName: string;
  onComplete: () => void;
  onError: (msg: string) => void;
};

export default function GenerationProgress({
  sessionToken,
  campaignId,
  campaignName,
  onComplete,
  onError,
}: Props) {
  const router = useRouter();
  const [total, setTotal] = useState(0);
  const [completed, setCompleted] = useState(0);
  const [done, setDone] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let attempts = 0;

    const poll = async () => {
      try {
        const res = await getCampaignGenerationStatus(sessionToken, campaignId);
        if (cancelled) return;

        if (res.ok && res.active === false) {
          setDone(true);
          setTotal(res.total || 0);
          setCompleted(res.completed || 0);
          onComplete();
          return;
        }

        if (res.ok) {
          setTotal(res.total || 0);
          setCompleted(res.completed || 0);
        }

        attempts = 0;
      } catch {
        attempts++;
        if (attempts > 5) {
          onError("Generation status check failed");
          return;
        }
      }

      if (!cancelled) setTimeout(poll, 600);
    };

    poll();
    return () => { cancelled = true; };
  }, [sessionToken, campaignId]);

  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

  const campaignNames = [
    { name: campaignName, status: done ? "done" : "generating", pct },
  ];

  return (
    <div className="flex flex-col items-center justify-center h-full px-6">
      <div className="max-w-lg w-full">
        <div className="text-center mb-10">
          <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto mb-4">
            {done ? (
              <Icon name="check_circle" className="text-4xl text-success" />
            ) : (
              <Icon name="auto_awesome" className="text-4xl text-primary animate-pulse" />
            )}
          </div>
          <h2 className="text-headline-md text-on-surface font-bold mb-1">
            {done ? "Drafts Generated" : "Generating Drafts"}
          </h2>
          <p className="text-body-md text-on-surface-variant/60">
            {done
              ? `${completed} draft${completed !== 1 ? "s" : ""} ready for review`
              : `Creating personalized outreach for ${total} lead${total !== 1 ? "s" : ""}`}
          </p>
        </div>

        <div className="space-y-3 mb-8">
          {campaignNames.map((c) => (
            <div
              key={c.name}
              className="rounded-xl border border-outline-variant/10 bg-surface-lowest p-4"
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3 min-w-0">
                  <div
                    className={`w-6 h-6 rounded-full flex items-center justify-center ${
                      c.status === "done"
                        ? "bg-success/20 text-success"
                        : "bg-primary/20 text-primary"
                    }`}
                  >
                    {c.status === "done" ? (
                      <Icon name="check_circle" className="text-sm" />
                    ) : (
                      <div className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                    )}
                  </div>
                  <span className="text-body-md text-on-surface font-medium truncate">
                    {c.name}
                  </span>
                </div>
                <span
                  className={`text-label-sm font-medium ${
                    c.status === "done" ? "text-success" : "text-primary"
                  }`}
                >
                  {c.status === "done" ? "Done" : `${c.pct}%`}
                </span>
              </div>
              <div className="w-full bg-outline-variant/10 rounded-full h-2 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    c.status === "done"
                      ? "bg-success"
                      : "bg-primary"
                  }`}
                  style={{ width: `${c.pct}%` }}
                />
              </div>
            </div>
          ))}
        </div>

        {!done ? (
          <div className="flex items-center justify-center gap-3 text-on-surface-variant/60">
            <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            <span className="text-label-sm">
              Generating personalized drafts for each lead...
            </span>
          </div>
        ) : (
          <div className="flex justify-center gap-3">
            <button
              onClick={() => router.push(`/draft`)}
              className="px-6 py-3 rounded-xl bg-primary text-on-primary font-bold hover:brightness-110 active:scale-95 transition-all text-sm"
            >
              Review Drafts
            </button>
            <button
              onClick={() => router.push("/campaigns")}
              className="px-6 py-3 rounded-xl border border-outline-variant/20 text-on-surface font-medium hover:border-primary/40 hover:text-primary transition-all text-sm"
            >
              Back to Campaigns
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
