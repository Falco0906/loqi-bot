"use client";

import { useCallback, useEffect, useMemo } from "react";
import { useCopilot } from "../../contexts/CopilotContext";
import ActivityFeed from "./ActivityFeed";
import QuickReplies from "./QuickReplies";
import SuggestedActions from "./SuggestedActions";
import CopilotComposer from "./CopilotComposer";
import Icon from "../shared/Icon";
import {
  STATE_LABELS,
  CLARIFICATION_PROMPT,
  CLARIFICATION_REPLIES,
  idleQuickReplies,
  type QuickReplyOption,
} from "../../lib/conversationMachine";

export default function CopilotPanel({ width = 380 }: { width?: number }) {
  const {
    open,
    setOpen,
    pageContext,
    executeAction,
    clear,
    conversationState,
    groups,
    activeGroupId,
    recentTask,
    startTask,
    answerClarification,
    acknowledge,
  } = useCopilot();

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && open) {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, setOpen]);

  const handleQuickReply = useCallback(
    (o: QuickReplyOption) => startTask(o.instruction),
    [startTask],
  );

  const handleClarificationReply = useCallback(
    (o: QuickReplyOption) => answerClarification(o.id),
    [answerClarification],
  );

  const handleSuggestedAction = useCallback(
    (action: Parameters<typeof executeAction>[0]) => {
      executeAction(action);
      acknowledge();
    },
    [executeAction, acknowledge],
  );

  const idleOptions = useMemo(
    () => idleQuickReplies(pageContext?.page),
    [pageContext?.page],
  );

  const working = conversationState === "working";

  return (
    <div
      className="shrink-0 h-full overflow-hidden flex justify-end bg-surface-lowest transition-[width] duration-200 ease-out"
      style={{ width: open ? width : 0 }}
      role="dialog"
      aria-label="Loqi OS"
    >
      <div
        className="w-[380px] max-w-[92vw] shrink-0 h-full flex flex-col overflow-hidden border-l border-outline-variant/15 shadow-glass"
        style={{ width }}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-outline-variant/10 shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-primary/15 flex items-center justify-center">
              <span className="material-symbols-outlined text-[16px] text-primary">smart_toy</span>
            </div>
            <span className="text-body-md text-on-surface font-bold">Loqi OS</span>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold ${
                working
                  ? "bg-primary/10 text-primary"
                  : conversationState === "clarification"
                    ? "bg-warning/10 text-warning"
                    : conversationState === "completed"
                      ? "bg-success/10 text-success"
                      : "bg-surface-high/60 text-on-surface-variant/60"
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  working ? "bg-primary animate-pulse" : "bg-current"
                }`}
              />
              {STATE_LABELS[conversationState]}
            </span>
            <button
              onClick={clear}
              className="p-1.5 rounded-lg text-on-surface-variant/50 hover:text-on-surface hover:bg-surface-high/60 transition-all duration-150 active:scale-95"
              title="Clear conversation"
              aria-label="Clear conversation"
            >
              <span className="material-symbols-outlined text-[18px]">delete_sweep</span>
            </button>
          </div>
        </div>

      {(conversationState === "idle" || conversationState === "completed") && (
        <>
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
            {groups.length === 0 && (
              <div className="flex flex-col items-center justify-center text-center px-6 py-12">
                <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center text-primary mb-4">
                  <Icon name="smart_toy" className="text-2xl" />
                </div>
                <p className="text-body-md text-on-surface font-bold mb-1">Loqi OS</p>
                <p className="text-label-sm text-on-surface-variant/60 max-w-xs">
                  Your workspace is ready. Tell me what to work on.
                </p>
              </div>
            )}
            {recentTask && conversationState === "idle" && (
              <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low/60 px-3.5 py-3">
                <p className="text-label-sm text-on-surface-variant/50 uppercase tracking-wider mb-1">
                  Recent task
                </p>
                <p className="text-body-sm text-on-surface font-semibold mb-0.5">
                  {recentTask.title}
                </p>
                <p className="text-body-sm text-on-surface-variant leading-relaxed mb-2.5">
                  {recentTask.summary}
                </p>
                {recentTask.actions.length > 0 && (
                  <SuggestedActions
                    actions={recentTask.actions}
                    onExecute={handleSuggestedAction}
                  />
                )}
              </div>
            )}
            {conversationState === "completed" && (
              <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low/60 px-3.5 py-3">
                <p className="text-body-sm text-on-surface font-semibold mb-2.5">
                  {recentTask?.summary ?? "Task complete."}
                </p>
                {recentTask && recentTask.actions.length > 0 && (
                  <SuggestedActions
                    actions={recentTask.actions}
                    onExecute={handleSuggestedAction}
                  />
                )}
                <button
                  type="button"
                  onClick={acknowledge}
                  className="mt-3 w-full rounded-lg border border-outline-variant/15 px-3 py-1.5 text-label-sm font-semibold text-on-surface-variant hover:text-on-surface hover:bg-surface-high/50 transition-all active:scale-[0.98]"
                >
                  Done
                </button>
              </div>
            )}
            <ActivityFeed groups={groups} activeGroupId={activeGroupId} />
          </div>
          {conversationState === "idle" && (
            <div className="shrink-0">
              <QuickReplies options={idleOptions} onSelect={handleQuickReply} />
              <CopilotComposer
                onSend={startTask}
                placeholder="Tell Loqi what to work on..."
              />
            </div>
          )}
          {conversationState === "completed" && (
            <div className="shrink-0 px-4 pt-1 pb-0.5">
              <div className="flex items-center gap-2 text-label-sm text-on-surface-variant/40">
                <span className="w-1.5 h-1.5 rounded-full bg-success/60" />
                Loqi OS
              </div>
            </div>
          )}
        </>
      )}

      {conversationState === "clarification" && (
        <>
          <div className="flex-1 overflow-y-auto px-4 py-4">
            <ActivityFeed groups={groups} activeGroupId={activeGroupId} />
            <div className="mt-4 bg-surface-container-low border border-outline-variant/10 rounded-xl px-4 py-3 feed-step-in">
              <p className="text-body-sm text-on-surface font-medium leading-relaxed">
                {CLARIFICATION_PROMPT}
              </p>
            </div>
          </div>
            <div className="shrink-0">
              <QuickReplies
                options={CLARIFICATION_REPLIES}
                onSelect={handleClarificationReply}
              />
              <CopilotComposer
                onSend={startTask}
                placeholder="Tell Loqi what to work on..."
              />
            </div>
        </>
      )}

      {conversationState === "working" && (
        <>
          <div className="flex-1 overflow-y-auto px-4 py-4">
            <ActivityFeed groups={groups} activeGroupId={activeGroupId} />
            <div className="mt-4 flex items-center gap-2 px-1">
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
              <span className="text-label-sm text-on-surface-variant/60">
                Loqi is working — your workspace stays ready.
              </span>
            </div>
          </div>
          <div className="shrink-0 px-4 pt-1 pb-0.5">
            <div className="flex items-center gap-2 text-label-sm text-on-surface-variant/40">
              <span className="w-1.5 h-1.5 rounded-full bg-success/60" />
              Loqi OS
            </div>
          </div>
        </>
      )}
      </div>
    </div>
  );
}
