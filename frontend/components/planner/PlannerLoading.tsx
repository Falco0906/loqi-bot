"use client";

import { useEffect, useState } from "react";
import Icon from "../shared/Icon";

const STAGES = [
  "Analyzing 20 selected companies...",
  "Finding buying patterns...",
  "Comparing commercial signals...",
  "Detecting common messaging opportunities...",
  "Grouping similar outreach strategies...",
  "Building campaign plan...",
];

export default function PlannerLoading({ leadCount }: { leadCount: number }) {
  const [stage, setStage] = useState(0);
  const [sub, setSub] = useState(0);

  useEffect(() => {
    setStage(0);
    setSub(0);

    const stageTimer = setInterval(() => {
      setStage((prev) => {
        if (prev >= STAGES.length - 1) {
          clearInterval(stageTimer);
          return prev;
        }
        return prev + 1;
      });
    }, 1600);

    const subTimer = setInterval(() => {
      setSub((prev) => (prev + 1) % 4);
    }, 300);

    return () => {
      clearInterval(stageTimer);
      clearInterval(subTimer);
    };
  }, [leadCount]);

  const current = STAGES[stage] ?? STAGES[STAGES.length - 1];
  const displayed = current.replace("20", String(leadCount));

  return (
    <div className="flex flex-col items-center justify-center py-24 px-6">
      <div className="relative mb-10">
        <div className="w-20 h-20 rounded-2xl bg-primary/10 flex items-center justify-center">
          <Icon name="psychology" className="text-4xl text-primary" />
        </div>
        <div className="absolute -top-1 -right-1">
          <span className="flex h-5 w-5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-40" />
            <span className="relative inline-flex rounded-full h-5 w-5 bg-primary" />
          </span>
        </div>
      </div>

      <div className="text-center mb-8">
        <p className="text-headline-sm text-on-surface font-bold mb-2">
          Analyzing your leads
        </p>
        <p className="text-body-md text-on-surface-variant/60">
          Building an outreach strategy for {leadCount} selected leads
        </p>
      </div>

      <div className="w-full max-w-md mx-auto">
        <div className="bg-surface-lowest rounded-xl border border-outline-variant/10 p-4 mb-6">
          <div className="flex items-center gap-3">
            <div className="flex flex-col items-center gap-1">
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className={`w-1.5 h-1.5 rounded-full transition-all duration-300 ${
                    i <= sub ? "bg-primary" : "bg-outline-variant/20"
                  }`}
                />
              ))}
            </div>
            <p className="text-body-md text-on-surface font-medium animate-fade-in">
              {displayed}
            </p>
          </div>
        </div>

        <div className="w-full bg-surface-lowest rounded-full h-2 overflow-hidden border border-outline-variant/10">
          <div
            className="h-full bg-gradient-to-r from-primary to-secondary rounded-full transition-all duration-700 ease-out"
            style={{ width: `${((stage + 1) / STAGES.length) * 100}%` }}
          />
        </div>

        <p className="text-center text-label-sm text-on-surface-variant/40 mt-3">
          AI is analyzing commercial signals across all selected leads
        </p>
      </div>
    </div>
  );
}
