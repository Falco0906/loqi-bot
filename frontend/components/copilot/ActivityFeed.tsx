"use client";

import { useEffect, useRef, useState } from "react";
import Icon from "../shared/Icon";
import type { TaskGroup, ActivityStep, StepStatus } from "../../lib/conversationMachine";

type Props = {
  groups: TaskGroup[];
  activeGroupId: string | null;
};

const KIND_ICONS: Record<TaskGroup["kind"], string> = {
  research: "explore",
  briefing: "auto_awesome",
  campaign: "campaign",
  inbox: "inbox",
};

function StepIcon({ status }: { status: StepStatus }) {
  if (status === "done") {
    return <Icon name="check_circle" className="text-success text-xs" />;
  }
  if (status === "active") {
    return <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />;
  }
  if (status === "error") {
    return <Icon name="error" className="text-error text-xs" />;
  }
  return <span className="w-1.5 h-1.5 rounded-full bg-outline-variant/30" />;
}

function StepRow({ step }: { step: ActivityStep }) {
  return (
    <div className="flex items-center gap-2.5 feed-step-in">
      <span className="w-4 flex items-center justify-center shrink-0">
        <StepIcon status={step.status} />
      </span>
      <span
        className={`text-body-sm leading-relaxed ${
          step.status === "done"
            ? "text-on-surface-variant/70"
            : step.status === "active"
              ? "text-on-surface font-medium"
              : step.status === "error"
                ? "text-error"
                : "text-on-surface-variant/40"
        }`}
      >
        {step.text}
      </span>
    </div>
  );
}

function GroupCard({ group, expanded, onToggle }: { group: TaskGroup; expanded: boolean; onToggle: () => void }) {
  const statusLabel =
    group.status === "complete" ? "Done" : group.status === "error" ? "Stopped" : "Working";

  return (
    <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low/60">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center gap-2.5 px-3.5 py-3 text-left"
        aria-expanded={expanded}
      >
        <span className="w-6 h-6 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
          <Icon name={KIND_ICONS[group.kind]} className="text-primary text-xs" />
        </span>
        <span className="flex-1 min-w-0">
          <span className="block text-body-sm text-on-surface font-semibold truncate">
            {group.title}
          </span>
          {group.status === "complete" && group.summary && (
            <span className="block text-label-sm text-on-surface-variant/60 truncate">
              {group.summary}
            </span>
          )}
        </span>
        <span
          className={`shrink-0 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold ${
            group.status === "complete"
              ? "bg-success/10 text-success"
              : group.status === "error"
                ? "bg-error/10 text-error"
                : "bg-primary/10 text-primary"
          }`}
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              group.status === "running" ? "bg-primary animate-pulse" : "bg-current"
            }`}
          />
          {statusLabel}
        </span>
        <Icon
          name="chevron_right"
          className={`text-on-surface-variant/40 text-sm shrink-0 transition-transform duration-200 ${expanded ? "rotate-90" : ""}`}
        />
      </button>
      {expanded && (
        <div className="px-3.5 pb-3 pt-0.5 space-y-2">
          {group.steps.map((step) => (
            <StepRow key={step.id} step={step} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function ActivityFeed({ groups, activeGroupId }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [groups]);

  if (groups.length === 0) return null;

  const sorted = [...groups].sort((a, b) => a.startedAt - b.startedAt);

  return (
    <div className="space-y-3">
      {sorted.map((group) => {
        const isActive = group.id === activeGroupId && group.status === "running";
        const expanded = isActive ? true : (collapsed[group.id] ?? !group.collapsed);
        return (
          <GroupCard
            key={group.id}
            group={group}
            expanded={expanded}
            onToggle={() =>
              setCollapsed((prev) => ({ ...prev, [group.id]: !expanded }))
            }
          />
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
