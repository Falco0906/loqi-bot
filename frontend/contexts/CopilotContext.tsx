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
import { ApiError, copilotMessage, getJob, getJobResults } from "../lib/api";
import {
  fetchBriefing,
  fetchDiscoveryFresh,
  prefetchDiscovery,
  prefetchDiscoveryList,
  prefetchMissionControl,
} from "../lib/repositories";
import {
  resolveTaskKind,
  nextState,
  TASKS,
  CLARIFICATION_REPLIES,
  completionActions,
  campaignStepActions,
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

export type CopilotMessage = {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  createdAt: number;
  actions?: CopilotAction[];
};

export type CopilotChat = {
  id: string;
  title: string;
  updatedAt: number;
  messages: CopilotMessage[];
};

type CopilotState = {
  open: boolean;
  pageContext: PageContext | null;
  conversationState: ConversationState;
  groups: TaskGroup[];
  activeGroupId: string | null;
  recentTask: RecentTask | null;
  activeChatId: string;
  chats: CopilotChat[];
  messages: CopilotMessage[];
};

type AgentOperation = {
  kind: "search_discovery";
  discovery_id: string;
  job_id: string;
};

type AgentTurn = { operation?: AgentOperation; error?: string };

type CopilotActions = {
  setOpen: (v: boolean) => void;
  setPageContext: (ctx: PageContext | null) => void;
  clear: () => void;
  executeAction: (action: CopilotAction) => void;
  registerHandler: (action: ActionType, handler: ActionHandler) => void;
  unregisterHandler: (action: ActionType) => void;
  startTask: (text: string) => boolean;
  answerClarification: (replyId: string) => void;
  acknowledge: () => void;
  newChat: () => void;
  switchChat: (chatId: string) => void;
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
let chatSeq = 0;
let messageSeq = 0;

function nextGroupId() {
  groupSeq += 1;
  return `grp-${groupSeq}`;
}

function nextStepId() {
  stepSeq += 1;
  return `stp-${stepSeq}`;
}

function nextChatId() {
  chatSeq += 1;
  return `chat-${Date.now()}-${chatSeq}`;
}

function nextMessageId() {
  messageSeq += 1;
  return `msg-${Date.now()}-${messageSeq}`;
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

function getTokenForActions(): string {
  try { return localStorage.getItem("loqi_active_session_token") || ""; }
  catch { return ""; }
}

const AGENT_ACTION_TYPES: ActionType[] = [
  "select_all", "clear_selection", "compare", "plan_campaign", "generate_drafts",
  "generate_strategy", "approve", "approve_all", "refine", "search", "save_campaign",
  "export_csv", "launch_campaign", "view_drafts", "open_campaign", "duplicate_campaign",
  "delete_campaign", "add_leads", "attach_discovery",
];

function parseAgentResponse(raw: string): { content: string; actions: CopilotAction[] } {
  const actions: CopilotAction[] = [];
  const content = raw.replace(/<<action:([^:>]+):([^>]+)>>/g, (_match, label: string, target: string) => {
    if (target.startsWith("/")) {
      actions.push({ type: "navigate", label: label.trim(), path: target.trim() });
    } else if (AGENT_ACTION_TYPES.includes(target.trim() as ActionType)) {
      actions.push({ type: "action", label: label.trim(), action: target.trim() as ActionType });
    }
    return "";
  }).trim();
  return { content, actions };
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
  const [pageContext, setPageContextState] = useState<PageContext | null>(null);
  const handlersRef = useRef<Map<ActionType, ActionHandler>>(new Map());

  const [conversationState, setConversationState] = useState<ConversationState>("idle");
  const [groups, setGroups] = useState<TaskGroup[]>([]);
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null);

  // ── PR-4.5: bounded conversation persistence (sessionStorage) ──
  // Survives client-side navigation AND full refresh within the same tab.
  // Cleared on logout via clearStoredTokens → clearClientCache path plus the
  // explicit purge below. Bounded to the last 3 groups / 40 steps.
  const persistConversation = useCallback((gs: TaskGroup[], activeId: string | null) => {
    try {
      const trimmed = gs.slice(0, 3).map(g => ({
        ...g,
        steps: g.steps.slice(0, 40),
      }));
      sessionStorage.setItem("loqi_copilot_conversation", JSON.stringify({
        groups: trimmed, activeGroupId: activeId,
      }));
    } catch { /* quota/private mode — persistence is best-effort */ }
  }, []);
  const [recentTask, setRecentTask] = useState<RecentTask | null>(null);
  const [activeChatId, setActiveChatId] = useState(() => nextChatId());
  const [chats, setChats] = useState<CopilotChat[]>([]);
  const [messages, setMessages] = useState<CopilotMessage[]>([]);

  const appendMessage = useCallback((message: Omit<CopilotMessage, "id" | "createdAt">) => {
    setMessages((previous) => [
      ...previous,
      { ...message, id: nextMessageId(), createdAt: Date.now() },
    ]);
  }, []);

  const pageContextRef = useRef<PageContext | null>(null);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem("loqi_copilot_conversation");
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed.groups) && parsed.groups.length > 0) {
        // Do not let late session hydration replace a task submitted during
        // the first render (the submitted group is the authoritative state).
        setGroups((current) => current.length > 0 ? current : parsed.groups.slice(0, 3));
        setActiveGroupId((current) => current ?? parsed.activeGroupId ?? null);
      }
    } catch { /* corrupted snapshot — start fresh */ }
  }, []);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem("loqi_copilot_chats");
      if (!raw) return;
      const parsed = JSON.parse(raw) as { activeChatId?: string; chats?: CopilotChat[] };
      if (!Array.isArray(parsed.chats)) return;
      setChats(parsed.chats.slice(0, 20));
      const active = parsed.chats.find((chat) => chat.id === parsed.activeChatId) || parsed.chats[0];
      if (active) {
        setActiveChatId(active.id);
        setMessages(active.messages || []);
      }
    } catch { /* corrupted snapshot — start fresh */ }
  }, []);

  useEffect(() => {
    if (messages.length === 0 && chats.length === 0) return;
    setChats((previous) => {
      const title = messages.find((message) => message.role === "user")?.content || "New conversation";
      const current: CopilotChat = {
        id: activeChatId,
        title: title.slice(0, 65),
        updatedAt: Date.now(),
        messages,
      };
      const withoutCurrent = previous.filter((chat) => chat.id !== activeChatId);
      return [current, ...withoutCurrent].slice(0, 20);
    });
  }, [activeChatId, messages]);

  useEffect(() => {
    try {
      sessionStorage.setItem("loqi_copilot_chats", JSON.stringify({ activeChatId, chats }));
    } catch { /* quota/private mode — persistence is best-effort */ }
  }, [activeChatId, chats]);

  const setPageContext = useCallback((ctx: PageContext | null) => {
    // Keep the ref in sync synchronously so startTask() — called immediately
    // after setPageContext() in the same handler — sees the fresh page.
    pageContextRef.current = ctx;
    setPageContextState(ctx);
  }, []);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const busyRef = useRef(false);
  const sessionRef = useRef(0);
  const activeGroupTitleRef = useRef("");

  const askAgent = useCallback(async (text: string, conversation: CopilotMessage[], requestSession: number): Promise<AgentTurn> => {
    appendMessage({ role: "tool", content: "Reviewing your request and current Loqi context…" });
    try {
      const response = await copilotMessage(getTokenForActions(), {
        text,
        currentPage: pageContextRef.current?.page,
        pageContext: pageContextRef.current?.data,
        availableActions: AGENT_ACTION_TYPES,
        messageHistory: conversation.slice(-12).map((message) => ({ role: message.role, text: message.content })),
      });
      if (sessionRef.current !== requestSession || !response.ok) return {};
      if (response.operation) return { operation: response.operation };
      const generated = response.messages?.find((message) => message.role === "assistant")?.text?.trim();
      if (!generated) return {};
      const parsed = parseAgentResponse(generated);
      appendMessage({ role: "assistant", content: parsed.content || generated, actions: parsed.actions });
      return {};
    } catch (error) {
      // The operational task owns success/failure. A generation outage must
      // never turn a real job into a false success or block its execution.
      return { error: error instanceof Error ? error.message : "Agent request failed" };
    }
    return {};
  }, [appendMessage]);

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
    (groupId: string, taskKind: TaskKind, summary: string, primaryPath?: string, extraActions?: CopilotAction[]) => {
      busyRef.current = false;
      finishGroup(groupId, summary, "complete");
      const task = TASKS[taskKind];
      setRecentTask({
        title: activeGroupTitleRef.current || task.label,
        summary,
        actions: completionActions(task, primaryPath, extraActions ?? null),
      });
      appendMessage({
        role: "assistant",
        content: summary,
        actions: completionActions(task, primaryPath, extraActions ?? null),
      });
      setGroups((prev) =>
        prev.map((g) => (g.id === groupId ? g : { ...g, collapsed: true })),
      );
      transition({ type: "work_finished" });
    },
    [finishGroup, transition, appendMessage],
  );

  const failWork = useCallback(
    (groupId: string, summary: string) => {
      busyRef.current = false;
      finishGroup(groupId, summary, "error");
      appendMessage({ role: "assistant", content: summary });
      // Failure is a distinct terminal state. The generic work_finished
      // transition would incorrectly render the completed/DONE surface.
      setConversationState("failed");
    },
    [finishGroup, appendMessage],
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

  const prepareDestination = useCallback(async (kind: TaskKind, discoveryId?: string) => {
    const task = TASKS[kind];
    router.prefetch(task.workspacePath);
    if (kind === "research") {
      if (discoveryId) {
        router.prefetch(`/discovery/${discoveryId}`);
        await prefetchDiscovery(discoveryId);
      } else {
        await prefetchDiscoveryList();
      }
    } else {
      await prefetchMissionControl();
    }
  }, [router]);

  const runResearch = useCallback(
    async (groupId: string, instruction: string, agentTurn?: Promise<AgentTurn>) => {
      const mySession = sessionRef.current;
      let discoveryId: string | null = null;
      let jobId: string | null = null;
      try {
        const turn = await agentTurn;
        const operation = turn?.operation;
        if (operation?.kind === "search_discovery") {
          discoveryId = operation.discovery_id;
          jobId = operation.job_id;
          console.info(`[discovery] agent accepted discovery=${discoveryId.slice(0, 8)} job=${jobId.slice(0, 8)}`);
        } else {
          failWork(groupId, `I couldn't start the Discovery operation${turn?.error ? `: ${turn.error}` : "."}`);
          return;
        }
      } catch {
        failWork(groupId, "Research couldn't start. Please try again.");
        return;
      }
      if (sessionRef.current !== mySession) return;
      if (!discoveryId || !jobId) {
        failWork(groupId, "Research couldn't start. Please try again.");
        return;
      }
      const discoveryPath = `/discovery/${discoveryId}`;

      let lastStage = "";
      let completed = false;
      // PR-P1.4: in-flight guard — never let job-status polls overlap when a
      // request outlives the 1.5s interval (e.g. while the backend is slow).
      let pollInFlight = false;
      const finish = async () => {
        if (completed) return;
        completed = true;
        stopPolling();
        let found = 0;
        try {
          const results = await getJobResults(jobId);
          if (sessionRef.current !== mySession) return;
          const leads = Array.isArray(results.leads) ? results.leads : [];
          found = leads.length;
          const scores = leads
            .map((l) => leadScore(l as Record<string, unknown>))
            .filter((s): s is number => s !== null);
          const matches = scores.length > 0 ? scores.filter((s) => s >= 70).length : leads.length;

          if (found > 0) addStep(groupId, `${found} compan${found === 1 ? "y" : "ies"} found.`, "done");
          if (matches > 0 && matches < found) addStep(groupId, `${matches} match your ICP.`, "done");

          markCurrentStep(groupId, "done");
          // Job completion precedes Discovery finalization in the backend.
          // Wait for the linked entity to become authoritative before
          // telling Copilot the requested operation succeeded.
          addStep(groupId, "Persisting Discovery results…", "active");
          let persisted = false;
          // Lead normalization/linking can take longer than the job terminal
          // update, especially for a first run. Keep this bounded, but do
          // not report a false persistence failure during normal finalization.
          for (let attempt = 0; attempt < 60; attempt += 1) {
            const discovery = await fetchDiscoveryFresh(discoveryId);
            if (!discovery) {
              failWork(groupId, "Discovery completed but its results could not be retrieved.");
              return;
            }
            if (discovery?.status === "completed") {
              persisted = true;
              break;
            }
            if (discovery?.status === "failed" || discovery?.status === "cancelled") break;
            await new Promise((resolve) => setTimeout(resolve, 250));
          }
          if (!persisted) {
            failWork(groupId, "Discovery results could not be persisted.");
            return;
          }
          if (sessionRef.current !== mySession) return;
          await prepareDestination("research", discoveryId);
          if (sessionRef.current !== mySession) return;
          addStep(groupId, "Discovery completed and results are ready.", "done");
          completeWork(
            groupId,
            "research",
            `Done — I found ${found} lead${found === 1 ? "" : "s"}.`,
            discoveryPath,
          );
        } catch {
          if (sessionRef.current !== mySession) return;
          // A terminal job with an unavailable result is not a successful
          // Copilot operation. Keep the failure visible instead of showing
          // DONE/View results for a run whose requested output was not read.
          failWork(groupId, "Discovery completed but its results could not be retrieved.");
        }
      };

      pollRef.current = setInterval(async () => {
        if (sessionRef.current !== mySession) {
          stopPolling();
          return;
        }
        if (pollInFlight) return;
        pollInFlight = true;
        try {
          const job = await getJob(jobId);
          const stage = job.stage ?? "";
          if (stage && stage !== lastStage) {
            lastStage = stage;
            if (job.status === "completed") {
              markCurrentStep(groupId, "done");
              void finish();
            } else if (job.status === "failed" || job.status === "cancelled") {
              stopPolling();
              failWork(groupId, "Research stopped early — nothing was changed.");
            } else if (!RESEARCH_SKIPPED_STAGES.has(stage)) {
              markCurrentStep(groupId, "done");
              addStep(groupId, RESEARCH_STAGE_LABELS[stage] ?? "Working on it…", "active");
            }
          } else if (job.status === "completed" && !completed) {
            void finish();
          }
        } catch (err) {
          // PR-4 HOTFIX: a 401 means the session is gone — stop hammering
          // and surface it instead of looping unauthenticated forever.
          if (err instanceof ApiError && err.status === 401) {
            stopPolling();
            failWork(groupId, "Your session expired — sign in again to continue.");
            return;
          }
          /* transient polling failure — keep polling */
        } finally {
          pollInFlight = false;
        }
      }, 1500);
    },
    [addStep, markCurrentStep, failWork, completeWork, prepareDestination, fetchDiscoveryFresh, stopPolling],
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
      const page = pageContextRef.current;
      const campaignId = page?.data?.campaignId as string | undefined;
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
      if (ready > 0) addStep(groupId, `${ready} campaign${ready === 1 ? "" : "s"} ready to launch.`, "done");
      if (drafts > 0) addStep(groupId, `${drafts} draft${drafts === 1 ? "" : "s"} waiting for your review.`, "done");
      if (ready === 0 && drafts === 0) addStep(groupId, "No campaign work waiting right now.", "done");
      markCurrentStep(groupId, "done");
      if (campaignId) {
        const step = page?.data?.step as string | undefined;
        addStep(groupId, step ? `Next step for this campaign: ${step}.` : "Opening the campaign…", "active");
        markCurrentStep(groupId, "done");
        completeWork(
          groupId,
          "campaign",
          "Here's where this campaign stands.",
          `/campaigns/${campaignId}`,
          campaignStepActions(campaignId, step),
        );
        return;
      }
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
    (kind: TaskKind, groupId: string, instruction: string, agentTurn?: Promise<AgentTurn>) => {
      switch (kind) {
        case "research":
          void runResearch(groupId, instruction, agentTurn);
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
    (kind: TaskKind, instruction: string, agentTurn?: Promise<AgentTurn>) => {
      const group = makeGroup(kind, taskTitle(kind, instruction), instruction);
      const groupId = group.id;
      activeGroupTitleRef.current = group.title;
      setGroups((prev) => [...prev.map((g) => ({ ...g, collapsed: true })), group]);
      setActiveGroupId(groupId);
      setRecentTask(null);
      busyRef.current = true;
      runTask(kind, groupId, instruction, agentTurn);
    },
    [runTask],
  );

  const startTask = useCallback(
    (text: string): boolean => {
      const trimmed = text.trim();
      if (!trimmed) return false;
      if (busyRef.current) return false;

      const previousMessages = messages;
      appendMessage({ role: "user", content: trimmed });

      const requestSession = sessionRef.current + 1;
      sessionRef.current = requestSession;
      const agentTurn = askAgent(trimmed, previousMessages, requestSession);
      setConversationState("working");
      void (async () => {
        const turn = await agentTurn;
        if (sessionRef.current !== requestSession) return;
        if (turn.operation?.kind === "search_discovery") {
          transition({ type: "instruction", kind: "research" });
          beginTask("research", trimmed, Promise.resolve(turn));
          return;
        }
        const kind = resolveTaskKind(trimmed, pageContextRef.current?.page);
        if (kind === "unknown") {
          busyRef.current = false;
          setRecentTask(null);
          setConversationState("idle");
          return;
        }
        transition({ type: "instruction", kind });
        beginTask(kind, trimmed, Promise.resolve(turn));
      })();
      return true;
    },
    [transition, beginTask, appendMessage, askAgent, messages],
  );

  const answerClarification = useCallback(
    (replyId: string) => {
      const reply = CLARIFICATION_REPLIES.find((r) => r.id === replyId);
      if (!reply || busyRef.current) return;
      const kind = resolveTaskKind(reply.instruction, pageContextRef.current?.page);
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
    setMessages([]);
    setConversationState("idle");
    try { sessionStorage.removeItem("loqi_copilot_conversation"); } catch { /* noop */ }
  }, [stopPolling]);

  const newChat = useCallback(() => {
    sessionRef.current += 1;
    stopPolling();
    busyRef.current = false;
    const id = nextChatId();
    setActiveChatId(id);
    setMessages([]);
    setGroups([]);
    setActiveGroupId(null);
    setRecentTask(null);
    setConversationState("idle");
  }, [stopPolling]);

  const switchChat = useCallback((chatId: string) => {
    if (busyRef.current) return;
    const chat = chats.find((item) => item.id === chatId);
    if (!chat) return;
    setActiveChatId(chat.id);
    setMessages(chat.messages || []);
    setGroups([]);
    setActiveGroupId(null);
    setRecentTask(null);
    setConversationState("idle");
  }, [chats]);

  // PR-4.5: persist on every conversation change (bounded by persistConversation).
  useEffect(() => {
    persistConversation(groups, activeGroupId);
  }, [groups, activeGroupId, persistConversation]);

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
      newChat,
      switchChat,
    }),
    [clear, executeAction, registerHandler, unregisterHandler, startTask, answerClarification, acknowledge, newChat, switchChat],
  );

  const state: CopilotState = {
    open,
    pageContext,
    conversationState,
    groups,
    activeGroupId,
    recentTask,
    activeChatId,
    chats,
    messages,
  };

  return (
    <CopilotActionsContext.Provider value={actions}>
      <CopilotStateContext.Provider value={state}>
        {children}
      </CopilotStateContext.Provider>
    </CopilotActionsContext.Provider>
  );
}
