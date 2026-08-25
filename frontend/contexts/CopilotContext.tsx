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
import { extractCopilotCapabilityResult, leadIdsFromResult, mergeCopilotResourceContext } from "../lib/copilot-integration";

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
  data?: Record<string, unknown>;
};

export type LeadOperationResult = {
  discovery_id: string;
  status: string;
  lead_count: number;
  leads: Array<Record<string, unknown>>;
};

export type CampaignOperationResult = {
  campaign_id?: string;
  campaign?: Record<string, unknown>;
  campaigns?: Array<Record<string, unknown>>;
  drafts?: Array<Record<string, unknown>>;
};

export type OutreachOperationResult = {
  draft?: Record<string, unknown>;
  drafts?: Array<Record<string, unknown>>;
  campaign_id?: string;
  operation?: Record<string, unknown>;
};

export type InboxOperationResult = {
  conversation_id?: string;
  conversation?: Record<string, unknown>;
  messages?: Array<Record<string, unknown>>;
  summary?: Record<string, unknown>;
  intelligence?: Record<string, unknown>;
  recommendation?: Record<string, unknown>;
  generation?: Record<string, unknown>;
};

export type KnowledgeOperationResult = {
  query?: string;
  categories?: string[];
  items?: Array<Record<string, unknown>>;
  sources?: Array<Record<string, unknown>>;
};

export type AnalyticsOperationResult = {
  metrics?: Record<string, unknown>;
  campaigns?: Array<Record<string, unknown>>;
  campaign?: Record<string, unknown>;
  campaign_id?: string;
  lead_count?: number;
};

export type CopilotResourceContext = {
  discoveryId?: string;
  selectedLeadIds?: string[];
  campaignId?: string;
  draftId?: string;
  conversationId?: string;
  knowledge?: { category?: string; itemId?: string; query?: string };
  analytics?: { scope?: string; campaignId?: string; campaignIds?: string[] };
};

function isLeadOperationResult(value: unknown): value is LeadOperationResult {
  if (!value || typeof value !== "object") return false;
  const result = value as Record<string, unknown>;
  return typeof result.discovery_id === "string" && Array.isArray(result.leads);
}

function isCampaignOperationResult(value: unknown): value is CampaignOperationResult {
  if (!value || typeof value !== "object") return false;
  const result = value as Record<string, unknown>;
  return Boolean(result.campaign || result.campaigns || result.drafts || result.campaign_id);
}

export type CopilotChat = {
  id: string;
  title: string;
  updatedAt: number;
  messages: CopilotMessage[];
  activeSearch?: ActiveSearch | null;
  leadResult?: LeadOperationResult | null;
  campaignResult?: CampaignOperationResult | null;
  outreachResult?: OutreachOperationResult | null;
  inboxResult?: InboxOperationResult | null;
  knowledgeResult?: KnowledgeOperationResult | null;
  analyticsResult?: AnalyticsOperationResult | null;
  resourceContext?: CopilotResourceContext | null;
};

export type ActiveSearch = {
  industry: string[];
  location: string[];
  decision_makers: string[];
  quantity: number | null;
  discovery_id?: string;
  job_id?: string;
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
  activeSearch: ActiveSearch | null;
  leadResult: LeadOperationResult | null;
  campaignResult: CampaignOperationResult | null;
  outreachResult: OutreachOperationResult | null;
  inboxResult: InboxOperationResult | null;
  knowledgeResult: KnowledgeOperationResult | null;
  analyticsResult: AnalyticsOperationResult | null;
  resourceContext: CopilotResourceContext | null;
};

type AgentOperation = {
  kind: "search_discovery";
  discovery_id: string;
  job_id: string;
  search_context: ActiveSearch;
};

type AgentTurn = {
  intent?: "conversation" | "discovery" | "discovery_refinement" | "read" | "action" | "clarification";
  operation?: AgentOperation;
  error?: string;
  leadResult?: LeadOperationResult;
  campaignResult?: CampaignOperationResult;
  outreachResult?: OutreachOperationResult;
  inboxResult?: InboxOperationResult;
  knowledgeResult?: KnowledgeOperationResult;
  analyticsResult?: AnalyticsOperationResult;
};

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
  const [activeSearch, setActiveSearchState] = useState<ActiveSearch | null>(null);
  const [leadResult, setLeadResult] = useState<LeadOperationResult | null>(null);
  const [campaignResult, setCampaignResult] = useState<CampaignOperationResult | null>(null);
  const [outreachResult, setOutreachResult] = useState<OutreachOperationResult | null>(null);
  const [inboxResult, setInboxResult] = useState<InboxOperationResult | null>(null);
  const [knowledgeResult, setKnowledgeResult] = useState<KnowledgeOperationResult | null>(null);
  const [analyticsResult, setAnalyticsResult] = useState<AnalyticsOperationResult | null>(null);
  const [resourceContext, setResourceContext] = useState<CopilotResourceContext | null>(null);
  const activeSearchRef = useRef<ActiveSearch | null>(null);

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
      const persistedChats = parsed.chats.filter((chat) =>
        Array.isArray(chat.messages) && chat.messages.some((message) => message.role === "user"),
      );
      setChats(persistedChats.slice(0, 20));
      const active = persistedChats.find((chat) => chat.id === parsed.activeChatId) || persistedChats[0];
      if (active) {
        setActiveChatId(active.id);
        setMessages(active.messages || []);
        activeSearchRef.current = active.activeSearch || null;
        setActiveSearchState(active.activeSearch || null);
        setLeadResult(active.leadResult || null);
        setCampaignResult(active.campaignResult || null);
        setOutreachResult(active.outreachResult || null);
        setInboxResult(active.inboxResult || null);
        setKnowledgeResult(active.knowledgeResult || null);
        setAnalyticsResult(active.analyticsResult || null);
        setResourceContext(active.resourceContext || null);
      }
    } catch { /* corrupted snapshot — start fresh */ }
  }, []);

  useEffect(() => {
    // A freshly opened chat is transient. Persist it only after the user has
    // actually sent a message; clicking "Start new chat" repeatedly must not
    // fill the history with empty conversations.
    if (!messages.some((message) => message.role === "user" && message.content.trim())) return;
    setChats((previous) => {
      const title = messages.find((message) => message.role === "user")?.content || "New conversation";
      const current: CopilotChat = {
        id: activeChatId,
        title: title.slice(0, 65),
        updatedAt: Date.now(),
        messages,
        activeSearch,
        leadResult,
        campaignResult,
        outreachResult,
        inboxResult,
        knowledgeResult,
        analyticsResult,
        resourceContext,
      };
      const withoutCurrent = previous.filter((chat) => chat.id !== activeChatId);
      return [current, ...withoutCurrent].slice(0, 20);
    });
  }, [activeChatId, messages, activeSearch, leadResult, campaignResult, outreachResult, inboxResult, knowledgeResult, analyticsResult, resourceContext]);

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
    if (ctx?.data) {
      const data = ctx.data;
      if (data.resource_context && typeof data.resource_context === "object") {
        // Page context is a partial update. Preserve the active Copilot resource
        // when navigating through list pages that have no selected resource.
        setResourceContext((previous) => ({
          ...previous,
          ...(data.resource_context as CopilotResourceContext),
        }));
        return;
      }
      setResourceContext((previous) => ({
        ...previous,
        discoveryId: String(data.discovery_id || data.discoveryId || previous?.discoveryId || "") || undefined,
        selectedLeadIds: Array.isArray(data.selected_lead_ids) ? data.selected_lead_ids.map(String) : previous?.selectedLeadIds,
        campaignId: String(data.campaign_id || data.campaignId || previous?.campaignId || "") || undefined,
        draftId: String(data.draft_id || data.draftId || previous?.draftId || "") || undefined,
        conversationId: String(data.conversation_id || data.conversationId || previous?.conversationId || "") || undefined,
        knowledge: data.knowledge && typeof data.knowledge === "object" ? data.knowledge as CopilotResourceContext["knowledge"] : previous?.knowledge,
        analytics: data.analytics && typeof data.analytics === "object" ? data.analytics as CopilotResourceContext["analytics"] : previous?.analytics,
      }));
    }
  }, []);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const busyRef = useRef(false);
  const sessionRef = useRef(0);
  const activeGroupTitleRef = useRef("");

  const askAgent = useCallback(async (text: string, conversation: CopilotMessage[], requestSession: number): Promise<AgentTurn> => {
    try {
      const response = await copilotMessage(getTokenForActions(), {
        text,
        currentPage: pageContextRef.current?.page,
        pageContext: mergeCopilotResourceContext(pageContextRef.current?.data, resourceContext),
        availableActions: AGENT_ACTION_TYPES,
        messageHistory: conversation.slice(-12).map((message) => ({ role: message.role, text: message.content })),
        activeSearch: activeSearchRef.current || undefined,
      });
      if (sessionRef.current !== requestSession) return {};
      if (response.operation?.kind === "search_discovery") {
        return { intent: response.intent, operation: response.operation };
      }
      const assistantMessage = response.messages?.find((message) => message.role === "assistant");
      const messageData = assistantMessage?.data;
      const rawTool = typeof messageData?.tool === "string" ? messageData.tool : "";
      const rawResult = messageData?.result;
      const leadResult = rawTool.startsWith("lead.") && isLeadOperationResult(rawResult)
        ? rawResult
        : undefined;
      const campaignResult = rawTool.startsWith("campaign.") && isCampaignOperationResult(rawResult)
        ? rawResult
        : undefined;
      const capabilityResult = extractCopilotCapabilityResult(rawTool, rawResult);
      const outreachResult = rawTool.startsWith("outreach.") && capabilityResult
        ? capabilityResult as OutreachOperationResult : undefined;
      const inboxResult = rawTool.startsWith("inbox.") && capabilityResult
        ? capabilityResult as InboxOperationResult : undefined;
      const knowledgeResult = rawTool.startsWith("knowledge.") && capabilityResult
        ? capabilityResult as KnowledgeOperationResult : undefined;
      const analyticsResult = rawTool.startsWith("analytics.") && capabilityResult
        ? capabilityResult as AnalyticsOperationResult : undefined;
      const generated = assistantMessage?.text?.trim() || "";
      const fallback = response.ok
        ? rawTool.startsWith("campaign.")
          ? "The campaign operation completed."
          : "The requested Loqi operation completed."
        : "Copilot could not complete that operation.";
      const parsed = parseAgentResponse(generated || fallback);
      appendMessage({
        role: "assistant",
        content: parsed.content || fallback,
        actions: parsed.actions,
        data: messageData,
      });
      return {
        intent: response.intent,
        error: response.ok ? undefined : generated || fallback,
        leadResult,
        campaignResult,
        outreachResult,
        inboxResult,
        knowledgeResult,
        analyticsResult,
      };
    } catch (error) {
      // The operational task owns success/failure. A generation outage must
      // never turn a real job into a false success or block its execution.
      return {
        intent: "clarification",
        error: error instanceof Error ? error.message : "Agent request failed",
      };
    }
    return {};
  }, [appendMessage, resourceContext]);

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
          const activeContext = {
            ...operation.search_context,
            discovery_id: operation.discovery_id,
            job_id: operation.job_id,
          };
          activeSearchRef.current = activeContext;
          setActiveSearchState(activeContext);
          setResourceContext((previous) => ({
            ...previous,
            discoveryId: operation.discovery_id,
          }));
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
      // Keep the composer guarded while intent is being resolved, but do not
      // expose a task/activity state before the backend returns an operation.
      busyRef.current = true;
      setRecentTask(null);
      const agentTurn = askAgent(trimmed, previousMessages, requestSession);
      void (async () => {
        const turn = await agentTurn;
        if (sessionRef.current !== requestSession) return;
        if (turn.operation?.kind === "search_discovery") {
          transition({ type: "instruction", kind: "research" });
          beginTask("research", trimmed, Promise.resolve(turn));
          return;
        }
        // The backend is authoritative for Copilot semantics. Do not let the
        // legacy local task classifier reinterpret a conversation/read/action
        // response as a product task.
        if (turn.intent) {
          busyRef.current = false;
          if (turn.leadResult) {
            setLeadResult(turn.leadResult);
            setResourceContext((previous) => ({
              ...previous,
              discoveryId: turn.leadResult?.discovery_id,
              selectedLeadIds: leadIdsFromResult(turn.leadResult),
            }));
          }
          if (turn.campaignResult) {
            setCampaignResult(turn.campaignResult);
            const campaign = turn.campaignResult.campaign;
            setResourceContext((previous) => ({
              ...previous,
              campaignId: String(turn.campaignResult?.campaign_id || campaign?.id || previous?.campaignId || "") || undefined,
            }));
          }
          if (turn.outreachResult) {
            setOutreachResult(turn.outreachResult);
            const draft = turn.outreachResult.draft || turn.outreachResult.drafts?.[0];
            setResourceContext((previous) => ({
              ...previous,
              draftId: String(draft?.id || previous?.draftId || "") || undefined,
              campaignId: String(turn.outreachResult?.campaign_id || draft?.campaign_id || previous?.campaignId || "") || undefined,
            }));
          }
          if (turn.inboxResult) {
            setInboxResult(turn.inboxResult);
            setResourceContext((previous) => ({
              ...previous,
              conversationId: String(turn.inboxResult?.conversation_id || turn.inboxResult?.conversation?.conversation_id || previous?.conversationId || "") || undefined,
            }));
          }
          if (turn.knowledgeResult) setKnowledgeResult(turn.knowledgeResult);
          if (turn.analyticsResult) {
            setAnalyticsResult(turn.analyticsResult);
            setResourceContext((previous) => ({
              ...previous,
              campaignId: String(turn.analyticsResult?.campaign_id || turn.analyticsResult?.campaign?.id || previous?.campaignId || "") || undefined,
            }));
          }
          setRecentTask(null);
          setConversationState(turn.error ? "failed" : "idle");
          return;
        }
        // A Copilot request must be owned by the backend decision contract.
        // If an older/malformed response has no intent, fail closed instead
        // of allowing the legacy keyword/page classifier to create a task.
        busyRef.current = false;
        setRecentTask(null);
        setConversationState("failed");
      })();
      return true;
    },
    [transition, beginTask, appendMessage, askAgent, messages],
  );

  const answerClarification = useCallback(
    (replyId: string) => {
      const reply = CLARIFICATION_REPLIES.find((r) => r.id === replyId);
      if (!reply || busyRef.current) return;
      // Clarification replies are ordinary Copilot turns. The backend must
      // classify the answer; the legacy local task classifier is not allowed
      // to convert it directly into a product task.
      void startTask(reply.instruction);
    },
    [startTask],
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
    setLeadResult(null);
    setCampaignResult(null);
    setOutreachResult(null);
    setInboxResult(null);
    setKnowledgeResult(null);
    setAnalyticsResult(null);
    setResourceContext(null);
    activeSearchRef.current = null;
    setActiveSearchState(null);
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
    setLeadResult(null);
    setCampaignResult(null);
    setOutreachResult(null);
    setInboxResult(null);
    setKnowledgeResult(null);
    setAnalyticsResult(null);
    setResourceContext(null);
    activeSearchRef.current = null;
    setActiveSearchState(null);
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
    activeSearchRef.current = chat.activeSearch || null;
    setActiveSearchState(chat.activeSearch || null);
    setLeadResult(chat.leadResult || null);
    setCampaignResult(chat.campaignResult || null);
    setOutreachResult(chat.outreachResult || null);
    setInboxResult(chat.inboxResult || null);
    setKnowledgeResult(chat.knowledgeResult || null);
    setAnalyticsResult(chat.analyticsResult || null);
    setResourceContext(chat.resourceContext || null);
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
    activeSearch,
    leadResult,
    campaignResult,
    outreachResult,
    inboxResult,
    knowledgeResult,
    analyticsResult,
    resourceContext,
  };

  return (
    <CopilotActionsContext.Provider value={actions}>
      <CopilotStateContext.Provider value={state}>
        {children}
      </CopilotStateContext.Provider>
    </CopilotActionsContext.Provider>
  );
}
