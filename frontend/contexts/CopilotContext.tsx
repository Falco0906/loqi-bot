"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { sendMessage } from "../lib/api";
import type {
  CopilotAction,
  ActionType,
  ActionHandler,
} from "../lib/actionRegistry";

export type { CopilotAction, ActionType, ActionHandler };

export type CopilotMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  actions?: CopilotAction[];
  created_at?: string;
};

export type PageContext = {
  page: string;
  data: Record<string, unknown>;
};

type CopilotContextType = {
  open: boolean;
  setOpen: (v: boolean) => void;
  messages: CopilotMessage[];
  sending: boolean;
  pageContext: PageContext | null;
  setPageContext: (ctx: PageContext | null) => void;
  send: (text: string) => Promise<void>;
  clear: () => void;
  executeAction: (action: CopilotAction) => void;
  registerHandler: (action: ActionType, handler: ActionHandler) => void;
  unregisterHandler: (action: ActionType) => void;
};

const CopilotContext = createContext<CopilotContextType | null>(null);

export function useCopilot() {
  const ctx = useContext(CopilotContext);
  if (!ctx) throw new Error("useCopilot must be used within CopilotProvider");
  return ctx;
}

export function CopilotProvider({
  children,
  sessionToken,
}: {
  children: ReactNode;
  sessionToken: string | null;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [pageContext, setPageContext] = useState<PageContext | null>(null);
  const handlersRef = useRef<Map<ActionType, ActionHandler>>(new Map());

  const registerHandler = useCallback(
    (action: ActionType, handler: ActionHandler) => {
      handlersRef.current.set(action, handler);
    },
    [],
  );

  const unregisterHandler = useCallback((action: ActionType) => {
    handlersRef.current.delete(action);
  }, []);

  const buildSystemPrompt = useCallback(() => {
    const ctx = pageContext;
    let prompt = `You are Loqi OS, the AI copilot for an outbound sales platform.

You can:
- Navigate between pages (Discovery, Campaigns, Draft Review, Campaign Intelligence, Mission Control)
- Answer questions about the user's data
- Execute actions on the current page

Available actions on this page:
${
  ctx?.page === "Discovery"
    ? "- select_all: Select all visible leads\n- clear_selection: Clear current selection\n- compare: Compare selected leads\n- plan_campaign: Create a campaign from selected leads\n- search: Search for leads\n- save_campaign: Save the current campaign\n- export_csv: Export leads to CSV"
    : ctx?.page === "Campaign"
      ? "- generate_drafts: Generate email drafts for this campaign"
      : ctx?.page === "Draft Review"
        ? "- approve: Approve the current draft\n- approve_all: Approve all pending drafts\n- refine: Refine the current draft"
        : "None specific"
}

Current page: ${ctx?.page || "unknown"}`;
    if (ctx?.data && Object.keys(ctx.data).length > 0) {
      prompt += `\n\nPage context:\n${JSON.stringify(ctx.data, null, 2)}`;
    }
    prompt += `\n\nKeep responses concise and actionable. When suggesting an action, include it in your response.
Format: <<action:label:action_type>> (e.g. <<action:Select All:select_all>>)
For navigation: <<action:label:/path>> (e.g. <<action:Discovery:/discovery>>)`;
    return prompt;
  }, [pageContext]);

  const executeAction = useCallback(
    async (action: CopilotAction) => {
      if (action.type === "navigate" && action.path) {
        router.push(action.path);
        setOpen(false);
        return;
      }
      if (action.type === "action" && action.action) {
        const handler = handlersRef.current.get(action.action);
        if (handler) {
          await handler(action.payload);
          setOpen(false);
          return;
        }
      }
    },
    [router],
  );

  const parseActions = useCallback(
    (text: string): { clean: string; actions: CopilotAction[] } => {
      const actions: CopilotAction[] = [];
      const clean = text.replace(
        /<<action:([^:]+):([^>]+)>>/g,
        (_m, label, target) => {
          if (target.startsWith("/")) {
            actions.push({ type: "navigate", label, path: target });
          } else {
            actions.push({ type: "action", label, action: target as ActionType });
          }
          return "";
        },
      );
      return { clean: clean.trim(), actions };
    },
    [],
  );

  const send = useCallback(
    async (text: string) => {
      if (!sessionToken || !text.trim() || sending) return;

      const userMsg: CopilotMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        text: text.trim(),
        created_at: new Date().toISOString(),
      };

      const systemPrompt = buildSystemPrompt();
      const fullText = `${systemPrompt}\n\nUser message: ${text.trim()}`;

      setMessages((prev) => [...prev, userMsg]);
      setSending(true);

      try {
        const res = await sendMessage(sessionToken, fullText);
        const assistantText =
          res.messages?.[res.messages.length - 1]?.text || "No response";
        const { clean, actions } = parseActions(assistantText);

        const assistantMsg: CopilotMessage = {
          id: `ai-${Date.now()}`,
          role: "assistant",
          text: clean || assistantText,
          actions: actions.length > 0 ? actions : undefined,
          created_at: new Date().toISOString(),
        };

        setMessages((prev) => [...prev, assistantMsg]);
      } catch {
        setMessages((prev) => [
          ...prev,
          {
            id: `ai-${Date.now()}`,
            role: "assistant",
            text: "Sorry, I encountered an error. Please try again.",
            created_at: new Date().toISOString(),
          },
        ]);
      } finally {
        setSending(false);
      }
    },
    [sessionToken, sending, buildSystemPrompt, parseActions],
  );

  const clear = useCallback(() => {
    setMessages([]);
  }, []);

  return (
    <CopilotContext.Provider
      value={{
        open,
        setOpen,
        messages,
        sending,
        pageContext,
        setPageContext,
        send,
        clear,
        executeAction,
        registerHandler,
        unregisterHandler,
      }}
    >
      {children}
    </CopilotContext.Provider>
  );
}
