"use client";

import { useEffect, useRef, useState } from "react";

const STAGING_LINES = [
  "Reviewing overnight activity...",
  "Summarizing campaigns...",
  "Prioritizing today's decisions...",
];

type Props = {
  greeting: string;
  lines: string[];
  suggestion?: string;
  onDone?: () => void;
};

export default function NarrativeBriefing({ greeting, lines, suggestion, onDone }: Props) {
  const [phase, setPhase] = useState<"staging" | "streaming" | "done">("staging");
  const [stageIndex, setStageIndex] = useState(0);
  const [visibleCount, setVisibleCount] = useState(0);
  const timersRef = useRef<number[]>([]);
  const doneRef = useRef(false);

  const total = lines.length + (suggestion ? 1 : 0);

  useEffect(() => {
    timersRef.current.push(
      window.setTimeout(() => setStageIndex(1), 550),
      window.setTimeout(() => setStageIndex(2), 1050),
      window.setTimeout(() => setPhase("streaming"), 1500)
    );

    if (total === 0) {
      timersRef.current.push(window.setTimeout(() => finish(true), 1600));
    }

    return () => {
      timersRef.current.forEach((t) => window.clearTimeout(t));
      timersRef.current = [];
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (phase !== "streaming") return;
    if (visibleCount >= total) {
      finish(true);
      return;
    }
    timersRef.current.push(window.setTimeout(() => setVisibleCount((c) => c + 1), 520));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, visibleCount, total]);

  function finish(notify: boolean) {
    if (doneRef.current) return;
    doneRef.current = true;
    setPhase("done");
    if (notify) onDone?.();
  }

  function skip() {
    timersRef.current.forEach((t) => window.clearTimeout(t));
    timersRef.current = [];
    setPhase("streaming");
    setVisibleCount(total);
    finish(false);
  }

  const visibleLines = lines.slice(0, visibleCount);
  const showSuggestion = Boolean(suggestion) && visibleCount > lines.length;

  return (
    <section
      className="space-y-6 select-none"
      onClick={skip}
      title="Click to skip"
    >
      {phase === "staging" && (
        <div className="space-y-2 animate-fade-in">
          <p className="text-lg text-on-surface-variant/70 font-light flex items-center gap-3">
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-ping-slow" />
            Preparing your morning briefing...
          </p>
          <p className="text-sm text-on-surface-variant/40 font-light">{STAGING_LINES[stageIndex]}</p>
        </div>
      )}

      {phase !== "staging" && (
        <div className="space-y-6">
          <h1 className="text-4xl md:text-5xl font-serif text-on-surface leading-tight tracking-tight font-normal animate-conversation-fade">
            {greeting || "Good morning"}
          </h1>
          {visibleLines.map((line, i) => (
            <p
              key={i}
              className={`text-xl text-on-surface-variant/60 leading-relaxed font-light ${
                i === 0 ? "animate-conversation-fade" : "animate-conversation-fade-delay-1"
              }`}
            >
              {line}
            </p>
          ))}
          {showSuggestion && (
            <p className="text-base text-primary font-medium mt-2 animate-conversation-fade">
              {suggestion}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
