"use client";

import { useCallback, useEffect, useMemo } from "react";
import { useCopilot, type CopilotMessage } from "../../contexts/CopilotContext";
import QuickReplies from "./QuickReplies";
import SuggestedActions from "./SuggestedActions";
import CopilotComposer from "./CopilotComposer";
import Icon from "../shared/Icon";
import { STATE_LABELS, CLARIFICATION_PROMPT, CLARIFICATION_REPLIES, idleQuickReplies, type QuickReplyOption } from "../../lib/conversationMachine";

function MessageBubble({ message, onAction }: { message: CopilotMessage; onAction: (action: Parameters<ReturnType<typeof useCopilot>["executeAction"]>[0]) => void }) {
  const user = message.role === "user";
  const tool = message.role === "tool";
  return (
    <div className={`flex ${user ? "justify-end" : "justify-start"}`}>
      <div className={`${user ? "max-w-[84%] bg-primary text-on-primary rounded-2xl rounded-br-md" : "max-w-[92%]"} ${tool ? "w-full rounded-xl border border-outline-variant/10 bg-surface-container-low/50 px-3.5 py-3" : "px-4 py-3"}`}>
        {!user && tool && <div className="flex items-center gap-2 mb-1.5 text-label-sm text-primary"><span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />Working</div>}
        {!user && !tool && <div className="flex items-center gap-2 mb-1.5 text-label-sm text-on-surface-variant/50"><span className="w-5 h-5 rounded-md bg-primary/10 text-primary flex items-center justify-center"><Icon name="smart_toy" className="text-xs" /></span>Loqi</div>}
        <p className={`whitespace-pre-wrap text-body-sm leading-relaxed ${user ? "" : "text-on-surface"}`}>{message.content}</p>
        {!user && message.actions && message.actions.length > 0 && <SuggestedActions actions={message.actions} onExecute={onAction} />}
      </div>
    </div>
  );
}

export default function CopilotPanel({ width = 380, variant = "sidebar" }: { width?: number; variant?: "sidebar" | "page" }) {
  const { open, setOpen, pageContext, executeAction, clear, conversationState, groups, activeGroupId, messages, chats, activeChatId, startTask, answerClarification, newChat, switchChat } = useCopilot();

  useEffect(() => {
    const handler = (event: KeyboardEvent) => { if (event.key === "Escape" && open) setOpen(false); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, setOpen]);

  const handleQuickReply = useCallback((option: QuickReplyOption) => startTask(option.instruction), [startTask]);
  const handleClarificationReply = useCallback((option: QuickReplyOption) => answerClarification(option.id), [answerClarification]);
  const handleAction = useCallback((action: Parameters<typeof executeAction>[0]) => { void executeAction(action); }, [executeAction]);
  const idleOptions = useMemo(() => idleQuickReplies(pageContext?.page), [pageContext?.page]);
  const working = conversationState === "working";

  const history = variant === "page" ? (
    <aside className="w-60 shrink-0 border-r border-outline-variant/10 bg-surface-container-low/30 flex flex-col">
      <div className="px-3 py-4 border-b border-outline-variant/10"><div className="flex items-center justify-between mb-3"><span className="text-label-sm uppercase tracking-wider text-on-surface-variant/60 font-semibold">Chats</span><Icon name="chat" className="text-sm text-on-surface-variant/40" /></div><button type="button" onClick={newChat} className="w-full flex items-center gap-2 rounded-lg bg-primary text-on-primary px-3 py-2 text-body-sm font-semibold hover:opacity-90 transition-opacity" aria-label="New chat"><Icon name="add" className="text-sm" />New chat</button></div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {chats.length === 0 ? <p className="px-2 py-3 text-label-sm text-on-surface-variant/45">No conversations yet</p> : chats.map((chat) => <button key={chat.id} type="button" onClick={() => switchChat(chat.id)} className={`w-full text-left rounded-lg px-2.5 py-2 ${chat.id === activeChatId ? "bg-primary/10" : "hover:bg-surface-high/40"}`}><p className="truncate text-body-sm text-on-surface font-medium">{chat.title}</p><p className="mt-0.5 text-[10px] uppercase tracking-wider text-on-surface-variant/45">{chat.messages.length} message{chat.messages.length === 1 ? "" : "s"}</p></button>)}
      </div>
    </aside>
  ) : null;

  return (
    <div className={variant === "page" ? "h-full w-full flex" : "shrink-0 h-full overflow-hidden flex justify-end bg-surface-lowest transition-[width] duration-200 ease-out"} style={variant === "page" ? undefined : { width: open ? width : 0 }} role="dialog" aria-label="Loqi OS">
      <div className={`${variant === "page" ? "w-full" : "w-[380px] max-w-[92vw] border-l border-outline-variant/15 shadow-glass"} h-full flex overflow-hidden`} style={variant === "page" ? undefined : { width }}>
        {history}
        <div className="flex-1 min-w-0 h-full flex flex-col overflow-hidden">
          {variant === "sidebar" && <header className="flex items-center justify-between px-4 py-3 border-b border-outline-variant/10 shrink-0"><div className="flex items-center gap-2.5"><div className="w-7 h-7 rounded-lg bg-primary/15 flex items-center justify-center"><Icon name="smart_toy" className="text-[16px] text-primary" /></div><span className="text-body-md text-on-surface font-bold">Loqi OS</span></div><div className="flex items-center gap-1.5"><span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold ${working ? "bg-primary/10 text-primary" : conversationState === "failed" ? "bg-error/10 text-error" : conversationState === "completed" ? "bg-success/10 text-success" : "bg-surface-high/60 text-on-surface-variant/60"}`}><span className={`w-1.5 h-1.5 rounded-full ${working ? "bg-primary animate-pulse" : "bg-current"}`} />{STATE_LABELS[conversationState]}</span><button type="button" onClick={newChat} className="p-1.5 rounded-lg text-on-surface-variant/50 hover:text-on-surface hover:bg-surface-high/60" title="New chat" aria-label="New chat"><Icon name="add" className="text-[18px]" /></button><button type="button" onClick={clear} className="p-1.5 rounded-lg text-on-surface-variant/50 hover:text-on-surface hover:bg-surface-high/60" title="Clear conversation" aria-label="Clear conversation"><Icon name="delete_sweep" className="text-[18px]" /></button></div></header>}
          <main className={`${variant === "page" ? "max-w-4xl w-full mx-auto" : "w-full"} flex-1 overflow-y-auto px-4 md:px-8 py-8 space-y-6`}>
            {messages.length === 0 && <div className="h-full min-h-64 flex flex-col items-center justify-center text-center px-6"><div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center text-primary mb-4"><Icon name="smart_toy" className="text-2xl" /></div><h1 className="text-xl font-serif text-on-surface mb-2">What can I help you with?</h1><p className="text-body-sm text-on-surface-variant/60 max-w-sm">Ask Loqi to research leads, review campaigns, or summarize what needs your attention.</p></div>}
            {messages.map((message) => <MessageBubble key={message.id} message={message} onAction={handleAction} />)}
            {working && activeGroupId && <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low/50 px-3.5 py-3 text-body-sm text-on-surface-variant/70"><div className="flex items-center gap-2 text-primary mb-1"><span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />Thinking</div>{groups.find((group) => group.id === activeGroupId)?.steps.at(-1)?.text || "Working on it…"}</div>}
            {conversationState === "clarification" && <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low px-4 py-3 text-body-sm text-on-surface">{CLARIFICATION_PROMPT}</div>}
          </main>
          <div className={`${variant === "page" ? "w-full max-w-4xl mx-auto" : "w-full"} shrink-0`}>{messages.length === 0 && <QuickReplies options={idleOptions} onSelect={handleQuickReply} />}{conversationState === "clarification" && <QuickReplies options={CLARIFICATION_REPLIES} onSelect={handleClarificationReply} />}<CopilotComposer onSend={startTask} disabled={working} placeholder={working ? "Loqi is working…" : "Message Loqi…"} /></div>
        </div>
      </div>
    </div>
  );
}
