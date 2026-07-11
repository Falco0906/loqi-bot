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
import { copilotMessage, createSession } from "../lib/api";
import type {
  CopilotAction,
  ActionType,
  ActionHandler,
} from "../lib/actionRegistry";

export type { CopilotAction, ActionType, ActionHandler };

const ACTIVE_SESSION_KEY = "loqi_active_session_token";

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

function storeToken(token: string) {
  try { localStorage.setItem(ACTIVE_SESSION_KEY, token); } catch { /* noop */ }
}

export function CopilotProvider({
  children,
  initialToken,
}: {
  children: ReactNode;
  initialToken: string | null;
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

  const buildAvailableActions = useCallback((): string[] => {
    const ctx = pageContext;
    if (!ctx) return [];
    const map: Record<string, string[]> = {
      Discovery: ["select_all", "clear_selection", "compare", "plan_campaign", "search", "save_campaign", "export_csv"],
      Campaign: ["generate_drafts"],
      "Draft Review": ["approve", "approve_all", "refine"],
    };
    return map[ctx.page] || [];
  }, [pageContext]);

  const send = useCallback(
    async (text: string) => {
      if (!text.trim() || sending) return;

      const userMsg: CopilotMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        text: text.trim(),
        created_at: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, userMsg]);
      setSending(true);

      try {
        let token = initialToken;
        if (!token) {
          const created = await createSession("Copilot User");
          token = created.session_token;
          storeToken(token);
        }

        const ctx = pageContext;
        const res = await copilotMessage(token, {
          text: text.trim(),
          currentPage: ctx?.page || "unknown",
          pageContext: ctx?.data,
          availableActions: buildAvailableActions(),
        });

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
    [initialToken, sending, pageContext, parseActions, buildAvailableActions],
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
