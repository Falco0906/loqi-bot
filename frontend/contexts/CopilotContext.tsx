"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  useRef,
  useEffect,
  type ReactNode,
} from "react";
import { useRouter, usePathname } from "next/navigation";
import { getJob, getJobResults } from "../lib/api";
import {
  fetchBriefing,
  startDiscoverySearch,
  prefetchDiscovery,
  prefetchMissionControl,
} from "../lib/repositories";
import {
  classifyInstruction,
  nextState,
  TASKS,
  CLARIFICATION_REPLIES,
  completionActions,
  taskTitle,
  researchFirstStep,
  KIND_FIRST_STEPS,
  RESEARCH_STAGE_LABELS,
  RESEARCH_SKIPPED_STAGES,
  type ConversationState,
  type TaskKind,
  type TaskGroup,
  type ActivityStep,
  type StepStatus,
  type TransitionEvent,
} from "../lib/conversationMachine";
import type {
  CopilotAction,
  ActionType,
  ActionHandler,
} from "../lib/actionRegistry";
import type { MCBriefingData } from "../lib/domain";

export type { CopilotAction, ActionType, ActionHandler };

export type PageContext = {
  page: string;
  data: Record<string, unknown>;
};

export type RecentTask = {
  title: string;
  summary: string;
  actions: CopilotAction[];
};

type CopilotState = {
  open: boolean;
  pageContext: PageContext | null;
  conversationState: ConversationState;
  groups: TaskGroup[];
  activeGroupId: string | null;
  recentTask: RecentTask | null;
};

type CopilotActions = {
  setOpen: (v: boolean) => void;
  setPageContext: (ctx: PageContext | null) => void;
  clear: () => void;
  executeAction: (action: CopilotAction) => void;
  registerHandler: (action: ActionType, handler: ActionHandler) => void;
  unregisterHandler: (action: ActionType) => void;
  startTask: (text: string) => void;
  answerClarification: (replyId: string) => void;
  acknowledge: () => void;
};

const CopilotStateContext = createContext<CopilotState | null>(null);
const CopilotActionsContext = createContext<CopilotActions | null>(null);

export function useCopilot(): CopilotState & CopilotActions {
  const state = useContext(CopilotStateContext);
  const actions = useContext(CopilotActionsContext);
  if (!state || !actions) {
    throw new Error("useCopilot must be used within CopilotProvider");
  }
  return { ...state, ...actions };
}

export function useCopilotActions(): CopilotActions {
  const actions = useContext(CopilotActionsContext);
  if (!actions) {
    throw new Error("useCopilotActions must be used within CopilotProvider");
  }
  return actions;
}

let groupSeq = 0;
let stepSeq = 0;

function nextGroupId() {
  groupSeq += 1;
  return `grp-${groupSeq}`;
}

function nextStepId() {
  stepSeq += 1;
  return `stp-${stepSeq}`;
}

function makeGroup(kind: TaskKind, title: string, instruction: string): TaskGroup {
  const firstStep: ActivityStep = {
    id: nextStepId(),
    text: kind === "research" ? researchFirstStep(instruction) : KIND_FIRST_STEPS[kind],
    status: "active",
  };
  return {
    id: nextGroupId(),
    title,
    kind,
    steps: [firstStep],
    summary: "",
    status: "running",
    startedAt: Date.now(),
    completedAt: null,
    collapsed: false,
  };
}

function leadScore(lead: Record<string, unknown>): number | null {
  const raw = lead.relevance_score ?? lead.score ?? lead.match_score;
  if (typeof raw !== "number") return null;
  return raw > 1 ? raw : raw * 100;
}

export function CopilotProvider({
  children,
}: {
  children: ReactNode;
}) {
  const router = useRouter();
  const pathnameRef = useRef<string | null>(null);
  pathnameRef.current = usePathname();

  const [open, setOpen] = useState(false);
  const [pageContext, setPageContext] = useState<PageContext | null>(null);
  const handlersRef = useRef<Map<ActionType, ActionHandler>>(new Map());

  const [conversationState, setConversationState] = useState<ConversationState>("idle");
  const [groups, setGroups] = useState<TaskGroup[]>([]);
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null);
  const [recentTask, setRecentTask] = useState<RecentTask | null>(null);

  const pageContextRef = useRef<PageContext | null>(null);
  pageContextRef.current = pageContext;

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const busyRef = useRef(false);
  const sessionRef = useRef(0);
  const activeGroupTitleRef = useRef("");

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const registerHandler = useCallback(
    (action: ActionType, handler: ActionHandler) => {
      handlersRef.current.set(action, handler);
    },
    [],
  );

  const unregisterHandler = useCallback((action: ActionType) => {
    handlersRef.current.delete(action);
  }, []);

  const executeAction = useCallback(
    async (action: CopilotAction) => {
      if (action.type === "navigate" && action.path) {
        router.push(action.path);
        return;
      }
      if (action.type === "action" && action.action) {
        const handler = handlersRef.current.get(action.action);
        if (handler) {
          await handler(action.payload);
          return;
        }
      }
    },
    [router],
  );

  /* ─── Phase 11D: grouped deterministic conversation state machine ─── */

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const updateGroup = useCallback(
    (groupId: string, fn: (g: TaskGroup) => TaskGroup) => {
      setGroups((prev) => prev.map((g) => (g.id === groupId ? fn(g) : g)));
    },
    [],
  );

  const markCurrentStep = useCallback(
    (groupId: string, status: StepStatus) => {
      updateGroup(groupId, (g) => {
        const steps = g.steps.map((s, i) =>
          i === g.steps.length - 1 && s.status === "active" ? { ...s, status } : s,
        );
        return { ...g, steps };
      });
    },
    [updateGroup],
  );

  const addStep = useCallback(
    (groupId: string, text: string, status: StepStatus) => {
      updateGroup(groupId, (g) => {
        const step: ActivityStep = { id: nextStepId(), text, status };
        return { ...g, steps: [...g.steps, step] };
      });
    },
    [updateGroup],
  );

  const advanceStep = useCallback(
    (groupId: string, text: string) => {
      updateGroup(groupId, (g) => {
        const steps = g.steps.map((s, i) =>
          i === g.steps.length - 1 && s.status === "active" ? { ...s, status: "done" as StepStatus } : s,
        );
        const step: ActivityStep = { id: nextStepId(), text, status: "active" };
        return { ...g, steps: [...steps, step] };
      });
    },
    [updateGroup],
  );

  const finishGroup = useCallback(
    (groupId: string, summary: string, status: "complete" | "error") => {
      updateGroup(groupId, (g) => ({
        ...g,
        status,
        summary,
        completedAt: Date.now(),
        steps: g.steps.map((s, i) =>
          i === g.steps.length - 1 && s.status === "active" ? { ...s, status: status === "complete" ? "done" : "error" } : s,
        ),
      }));
    },
    [updateGroup],
  );

  const transition = useCallback((event: TransitionEvent) => {
    setConversationState((prev) => nextState(prev, event));
  }, []);

  const completeWork = useCallback(
    (groupId: string, taskKind: TaskKind, summary: string) => {
      busyRef.current = false;
      finishGroup(groupId, summary, "complete");
      const task = TASKS[taskKind];
      setRecentTask({
        title: activeGroupTitleRef.current || task.label,
        summary,
        actions: completionActions(task),
      });
      setGroups((prev) =>
        prev.map((g) => (g.id === groupId ? g : { ...g, collapsed: true })),
      );
      transition({ type: "work_finished" });
    },
    [finishGroup, transition],
  );

  const failWork = useCallback(
    (groupId: string, summary: string) => {
      busyRef.current = false;
      finishGroup(groupId, summary, "error");
      transition({ type: "work_finished" });
    },
    [finishGroup, transition],
  );

  const navigateTo = useCallback(
    (path: string): boolean => {
      const current = pathnameRef.current ?? "";
      if (current.startsWith(path)) return false;
      router.push(path);
      return true;
    },
    [router],
  );

  const prepareDestination = useCallback(async (kind: TaskKind) => {
    const task = TASKS[kind];
    router.prefetch(task.workspacePath);
    if (kind === "research") await prefetchDiscovery();
    else await prefetchMissionControl();
  }, [router]);

  const runResearch = useCallback(
    async (groupId: string, instruction: string) => {
      const task = TASKS.research;
      const mySession = sessionRef.current;
      let jobId: string | null = null;
      try {
        jobId = await startDiscoverySearch(instruction);
      } catch {
        failWork(groupId, "Research couldn't start. Please try again.");
        return;
      }
      if (sessionRef.current !== mySession) return;
      if (!jobId) {
        failWork(groupId, "Research couldn't start. Please try again.");
        return;
      }

      let lastStage = "";
      let completed = false;
      const finish = async () => {
        if (completed) return;
        completed = true;
        stopPolling();
        try {
          const results = await getJobResults(jobId!);
          if (sessionRef.current !== mySession) return;
          const leads = Array.isArray(results.leads) ? results.leads : [];
          const found = leads.length;
          const scores = leads
            .map((l) => leadScore(l as Record<string, unknown>))
            .filter((s): s is number => s !== null);
          const matches = scores.length > 0 ? scores.filter((s) => s >= 70).length : leads.length;

          if (found > 0) addStep(groupId, `${found} compan${found === 1 ? "y" : "ies"} found.`, "done");
          if (matches > 0 && matches < found) addStep(groupId, `${matches} match your ICP.`, "done");

          markCurrentStep(groupId, "done");
          addStep(groupId, `Preparing ${task.workspaceLabel}…`, "active");
          await prepareDestination("research");
          if (sessionRef.current !== mySession) return;
          markCurrentStep(groupId, "done");
          addStep(groupId, `Opening ${task.workspaceLabel}…`, "active");
          navigateTo(task.workspacePath);
          markCurrentStep(groupId, "done");
          addStep(groupId, "Ready for review.", "done");
          completeWork(
            groupId,
            "research",
            found > 0
              ? `Found ${found} compan${found === 1 ? "y" : "ies"} worth reviewing.`
              : "No new prospects matched your ICP this time.",
          );
        } catch {
          failWork(groupId, "Research stopped early — nothing was changed.");
        }
      };

      pollRef.current = setInterval(async () => {
        if (sessionRef.current !== mySession) {
          stopPolling();
          return;
        }
        try {
          const job = await getJob(jobId!);
          const stage = job.stage ?? "";
          if (stage && stage !== lastStage) {
            lastStage = stage;
            if (stage === "Complete") {
              markCurrentStep(groupId, "done");
              void finish();
            } else if (stage === "Failed" || stage === "Cancelled") {
              stopPolling();
              failWork(groupId, "Research stopped early — nothing was changed.");
            } else if (!RESEARCH_SKIPPED_STAGES.has(stage)) {
              markCurrentStep(groupId, "done");
              addStep(groupId, RESEARCH_STAGE_LABELS[stage] ?? "Working on it…", "active");
            }
          } else if (job.status === "completed" && !completed) {
            void finish();
          }
        } catch {
          /* transient polling failure — keep polling */
        }
      }, 1500);
    },
    [addStep, markCurrentStep, failWork, completeWork, navigateTo, prepareDestination, stopPolling],
  );

  const runBriefingTask = useCallback(
    async (groupId: string) => {
      const task = TASKS.briefing;
      const mySession = sessionRef.current;
      let briefing: MCBriefingData | null = null;
      try {
        briefing = await fetchBriefing();
      } catch {
        failWork(groupId, "I couldn't reach the briefing right now.");
        return;
      }
      if (sessionRef.current !== mySession) return;
      if (!briefing) {
        failWork(groupId, "I couldn't reach the briefing right now.");
        return;
      }
      const lines = briefing.briefing?.lines ?? [];
      const shown = lines.slice(0, 2);
      if (shown.length > 0) {
        markCurrentStep(groupId, "done");
        shown.forEach((line, i) =>
          addStep(groupId, line, i === shown.length - 1 ? "active" : "done"),
        );
      }
      const waiting = briefing.waitingOnYou?.length ?? 0;
      const handled = briefing.loqiHandled?.length ?? 0;
      if (waiting > 0) addStep(groupId, `${waiting} item${waiting === 1 ? "" : "s"} waiting on your decision.`, "done");
      if (handled > 0) addStep(groupId, `Loqi handled ${handled} item${handled === 1 ? "" : "s"} while you were away.`, "done");
      if (waiting === 0 && handled === 0 && shown.length === 0) {
        addStep(groupId, "Nothing new since your last briefing.", "done");
      }
      markCurrentStep(groupId, "done");
      addStep(groupId, `Preparing ${task.workspaceLabel}…`, "active");
      await prepareDestination("briefing");
      if (sessionRef.current !== mySession) return;
      markCurrentStep(groupId, "done");
      addStep(groupId, `Opening ${task.workspaceLabel}…`, "active");
      const moved = navigateTo(task.workspacePath);
      if (!moved) {
        updateGroup(groupId, (g) => {
          const steps = g.steps.map((s, i) =>
            i === g.steps.length - 1 && s.status === "active"
              ? { ...s, text: `${task.workspaceLabel} is ready.`, status: "done" as StepStatus }
              : s,
          );
          return { ...g, steps };
        });
      } else {
        markCurrentStep(groupId, "done");
      }
      addStep(groupId, "Ready for review.", "done");
      completeWork(groupId, "briefing", "Your briefing is ready.");
    },
    [addStep, markCurrentStep, failWork, completeWork, navigateTo, prepareDestination, updateGroup],
  );

  const runCampaignTask = useCallback(
    async (groupId: string) => {
      const task = TASKS.campaign;
      const mySession = sessionRef.current;
      let briefing: MCBriefingData | null = null;
      try {
        briefing = await fetchBriefing();
      } catch {
        failWork(groupId, "I couldn't reach campaign data right now.");
        return;
      }
      if (sessionRef.current !== mySession) return;
      if (!briefing) {
        failWork(groupId, "I couldn't reach campaign data right now.");
        return;
      }
      const ready = briefing.topPriorities.filter((c) => c.reasonCode === "campaign_ready").length;
      const drafts = briefing.waitingOnYou.filter((c) => c.reasonCode === "draft_review_required").length;
      if (ready > 0) addStep(groupId, `${ready} campaign${ready === 1 ? "" : "s"} ready to review.`, "done");
      if (drafts > 0) addStep(groupId, `${drafts} draft${drafts === 1 ? "" : "s"} waiting for your review.`, "done");
      if (ready === 0 && drafts === 0) addStep(groupId, "No campaign work waiting right now.", "done");
      markCurrentStep(groupId, "done");
      addStep(groupId, `Preparing ${task.workspaceLabel}…`, "active");
      await prepareDestination("campaign");
      if (sessionRef.current !== mySession) return;
      markCurrentStep(groupId, "done");
      addStep(groupId, `Opening ${task.workspaceLabel}…`, "active");
      navigateTo(task.workspacePath);
      markCurrentStep(groupId, "done");
      addStep(groupId, "Ready for review.", "done");
      completeWork(groupId, "campaign", "Campaigns are ready for your review.");
    },
    [addStep, markCurrentStep, failWork, completeWork, navigateTo, prepareDestination],
  );

  const runInboxTask = useCallback(
    async (groupId: string) => {
      const task = TASKS.inbox;
      const mySession = sessionRef.current;
      let briefing: MCBriefingData | null = null;
      try {
        briefing = await fetchBriefing();
      } catch {
        failWork(groupId, "I couldn't reach your inbox right now.");
        return;
      }
      if (sessionRef.current !== mySession) return;
      if (!briefing) {
        failWork(groupId, "I couldn't reach your inbox right now.");
        return;
      }
      const waiting = briefing.waitingOnYou ?? [];
      const replies = waiting.filter((c) => c.reasonCode === "new_reply_received").length;
      if (replies > 0) addStep(groupId, `${replies} reply${replies === 1 ? "" : "s"} need${replies === 1 ? "s" : ""} your decision.`, "done");
      else addStep(groupId, "No replies need your attention right now.", "done");
      markCurrentStep(groupId, "done");
      addStep(groupId, `Preparing ${task.workspaceLabel}…`, "active");
      await prepareDestination("inbox");
      if (sessionRef.current !== mySession) return;
      markCurrentStep(groupId, "done");
      addStep(groupId, `Opening ${task.workspaceLabel}…`, "active");
      navigateTo(task.workspacePath);
      markCurrentStep(groupId, "done");
      addStep(groupId, "Ready for review.", "done");
      completeWork(groupId, "inbox", "Your inbox is up to date.");
    },
    [addStep, markCurrentStep, failWork, completeWork, navigateTo, prepareDestination],
  );

  const runTask = useCallback(
    (kind: TaskKind, groupId: string, instruction: string) => {
      switch (kind) {
        case "research":
          void runResearch(groupId, instruction);
          break;
        case "briefing":
          void runBriefingTask(groupId);
          break;
        case "campaign":
          void runCampaignTask(groupId);
          break;
        case "inbox":
          void runInboxTask(groupId);
          break;
      }
    },
    [runResearch, runBriefingTask, runCampaignTask, runInboxTask],
  );

  const beginTask = useCallback(
    (kind: TaskKind, instruction: string) => {
      const group = makeGroup(kind, taskTitle(kind, instruction), instruction);
      const groupId = group.id;
      activeGroupTitleRef.current = group.title;
      setGroups((prev) => [...prev.map((g) => ({ ...g, collapsed: true })), group]);
      setActiveGroupId(groupId);
      setRecentTask(null);
      busyRef.current = true;
      runTask(kind, groupId, instruction);
    },
    [runTask],
  );

  const startTask = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || busyRef.current) return;

      const kind = classifyInstruction(trimmed);
      if (kind === "unknown") {
        setRecentTask(null);
        transition({ type: "instruction", kind });
        return;
      }
      sessionRef.current += 1;
      transition({ type: "instruction", kind });
      beginTask(kind, trimmed);
    },
    [transition, beginTask],
  );

  const answerClarification = useCallback(
    (replyId: string) => {
      const reply = CLARIFICATION_REPLIES.find((r) => r.id === replyId);
      if (!reply || busyRef.current) return;
      const kind = classifyInstruction(reply.instruction);
      if (kind === "unknown") return;
      sessionRef.current += 1;
      transition({ type: "answer" });
      beginTask(kind, reply.instruction);
    },
    [transition, beginTask],
  );

  const acknowledge = useCallback(() => {
    if (busyRef.current) return;
    stopPolling();
    setConversationState((prev) => nextState(prev, { type: "acknowledge" }));
    setActiveGroupId(null);
    setGroups((prev) => prev.map((g) => (g.status !== "running" ? { ...g, collapsed: true } : g)));
  }, [stopPolling]);

  const clear = useCallback(() => {
    sessionRef.current += 1;
    stopPolling();
    busyRef.current = false;
    setGroups([]);
    setActiveGroupId(null);
    setRecentTask(null);
    setConversationState("idle");
  }, [stopPolling]);

  const actions: CopilotActions = useMemo(
    () => ({
      setOpen,
      setPageContext,
      clear,
      executeAction,
      registerHandler,
      unregisterHandler,
      startTask,
      answerClarification,
      acknowledge,
    }),
    [clear, executeAction, registerHandler, unregisterHandler, startTask, answerClarification, acknowledge],
  );

  const state: CopilotState = {
    open,
    pageContext,
    conversationState,
    groups,
    activeGroupId,
    recentTask,
  };

  return (
    <CopilotActionsContext.Provider value={actions}>
      <CopilotStateContext.Provider value={state}>
        {children}
      </CopilotStateContext.Provider>
    </CopilotActionsContext.Provider>
  );
}
