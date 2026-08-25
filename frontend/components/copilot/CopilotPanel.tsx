"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useCopilot, type CopilotMessage, type LeadOperationResult, type CampaignOperationResult } from "../../contexts/CopilotContext";
import QuickReplies from "./QuickReplies";
import SuggestedActions from "./SuggestedActions";
import CopilotComposer from "./CopilotComposer";
import Icon from "../shared/Icon";
import { CLARIFICATION_PROMPT, CLARIFICATION_REPLIES, idleQuickReplies, type QuickReplyOption } from "../../lib/conversationMachine";

function MessageBubble({ message, onAction }: { message: CopilotMessage; onAction: (action: Parameters<ReturnType<typeof useCopilot>["executeAction"]>[0]) => void }) {
  const user = message.role === "user";
  const tool = message.role === "tool";
  const result = message.data?.result as LeadOperationResult | undefined;
  const leadTool = typeof message.data?.tool === "string" && message.data.tool.startsWith("lead.");
  const campaignResult = message.data?.result as CampaignOperationResult | undefined;
  const campaignTool = typeof message.data?.tool === "string" && message.data.tool.startsWith("campaign.");
  const outreachResult = message.data?.result as { draft?: Record<string, unknown>; drafts?: Array<Record<string, unknown>> } | undefined;
  const outreachTool = typeof message.data?.tool === "string" && message.data.tool.startsWith("outreach.");
  const inboxResult = message.data?.result as { conversation?: Record<string, unknown>; summary?: Record<string, unknown>; generation?: Record<string, unknown>; messages?: Array<Record<string, unknown>> } | undefined;
  const inboxTool = typeof message.data?.tool === "string" && message.data.tool.startsWith("inbox.");
  const knowledgeResult = message.data?.result as { items?: Array<Record<string, unknown>>; sources?: Array<Record<string, unknown>> } | undefined;
  const knowledgeTool = typeof message.data?.tool === "string" && message.data.tool.startsWith("knowledge.");
  const analyticsResult = message.data?.result as { metrics?: Record<string, unknown>; campaigns?: Array<Record<string, unknown>> } | undefined;
  const analyticsTool = typeof message.data?.tool === "string" && message.data.tool.startsWith("analytics.");
  return (
    <div className={`flex ${user ? "justify-end" : "justify-start"}`}>
      <div className={`${user ? "max-w-[84%] bg-primary text-on-primary rounded-2xl rounded-br-md" : "max-w-[92%]"} ${tool ? "w-full rounded-xl border border-outline-variant/10 bg-surface-container-low/50 px-3.5 py-3" : "px-4 py-3"}`}>
        {!user && tool && <div className="flex items-center gap-2 mb-1.5 text-label-sm text-primary"><span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />Working</div>}
        {!user && !tool && <div className="flex items-center gap-2 mb-1.5 text-label-sm text-on-surface-variant/50"><span className="w-5 h-5 rounded-md bg-primary/10 text-primary flex items-center justify-center"><Icon name="smart_toy" className="text-xs" /></span>Loqi</div>}
        <p className={`whitespace-pre-wrap text-body-sm leading-relaxed ${user ? "" : "text-on-surface"}`}>{message.content}</p>
        {!user && leadTool && result && Array.isArray(result.leads) && result.leads.length > 0 && (
          <div className="mt-3 space-y-1.5" data-testid="copilot-lead-results">
            {result.leads.map((lead, index) => {
              const name = String(lead.name || [lead.first_name, lead.last_name].filter(Boolean).join(" ") || lead.company || `Lead ${index + 1}`);
              const detail = [lead.title, lead.company, lead.location_label || lead.city].filter(Boolean).map(String).join(" · ");
              return (
                <div key={String(lead.id || index)} className="rounded-lg border border-outline-variant/10 bg-surface-container-low/50 px-3 py-2">
                  <p className="text-body-sm font-medium text-on-surface">{index + 1}. {name}</p>
                  {detail && <p className="text-label-sm text-on-surface-variant/60 mt-0.5">{detail}</p>}
                </div>
              );
            })}
          </div>
        )}
        {!user && campaignTool && campaignResult && (
          <div className="mt-3 space-y-1.5" data-testid="copilot-campaign-results">
            {(campaignResult.campaigns || []).map((campaign, index) => (
              <div key={String(campaign.id || index)} className="rounded-lg border border-outline-variant/10 bg-surface-container-low/50 px-3 py-2">
                <p className="text-body-sm font-medium text-on-surface">{String(campaign.name || `Campaign ${index + 1}`)}</p>
                <p className="text-label-sm text-on-surface-variant/60 mt-0.5">{String(campaign.status || "planning")} · {Number(campaign.lead_count || 0)} leads</p>
              </div>
            ))}
            {campaignResult.campaign && (
              <div className="rounded-lg border border-outline-variant/10 bg-surface-container-low/50 px-3 py-2">
                <p className="text-body-sm font-medium text-on-surface">{String(campaignResult.campaign.name || "Campaign")}</p>
                <p className="text-label-sm text-on-surface-variant/60 mt-0.5">{String(campaignResult.campaign.status || "planning")} · {Number(campaignResult.campaign.lead_count || 0)} leads</p>
              </div>
            )}
            {campaignResult.drafts && <p className="text-label-sm text-on-surface-variant/60">{campaignResult.drafts.length} draft(s)</p>}
          </div>
        )}
        {!user && outreachTool && outreachResult && (
          <div className="mt-3 space-y-1.5" data-testid="copilot-outreach-results">
            {(outreachResult.drafts || (outreachResult.draft ? [outreachResult.draft] : [])).map((draft, index) => (
              <div key={String(draft.id || index)} className="rounded-lg border border-outline-variant/10 bg-surface-container-low/50 px-3 py-2">
                <p className="text-body-sm font-medium text-on-surface">{String(draft.subject || `Draft ${index + 1}`)}</p>
                <p className="text-label-sm text-on-surface-variant/60 mt-0.5">{String(draft.status || "pending")}{draft.text ? ` · ${String(draft.text).slice(0, 120)}` : ""}</p>
              </div>
            ))}
          </div>
        )}
        {!user && inboxTool && inboxResult && (
          <div className="mt-3 space-y-1.5" data-testid="copilot-inbox-results">
            {inboxResult.summary && <div className="rounded-lg border border-outline-variant/10 bg-surface-container-low/50 px-3 py-2"><p className="text-label-sm text-on-surface-variant/70">{String(inboxResult.summary.last_summary || inboxResult.summary.next_action || "Conversation summary available")}</p></div>}
            {inboxResult.generation && <div className="rounded-lg border border-outline-variant/10 bg-surface-container-low/50 px-3 py-2"><p className="text-body-sm font-medium text-on-surface">Reply draft</p><p className="text-label-sm text-on-surface-variant/60 mt-0.5">{String((((inboxResult.generation.variants as Array<Record<string, unknown>> | undefined)?.[0]?.drafts as Array<Record<string, unknown>> | undefined)?.[0]?.content) || "Draft generated")}</p></div>}
            {inboxResult.conversation && <p className="text-label-sm text-on-surface-variant/60">{String(inboxResult.conversation.subject || "Conversation")}</p>}
          </div>
        )}
        {!user && knowledgeTool && knowledgeResult && (knowledgeResult.items?.length || knowledgeResult.sources?.length) ? (
          <div className="mt-3 space-y-1.5" data-testid="copilot-knowledge-results">
            {(knowledgeResult.items || []).map((item, index) => (
              <div key={String(item.id || index)} className="rounded-lg border border-outline-variant/10 bg-surface-container-low/50 px-3 py-2">
                <p className="text-body-sm font-medium text-on-surface">{String(item.title || "Knowledge")}</p>
                <p className="text-label-sm text-on-surface-variant/60 mt-0.5">{String(item.summary || item.category || "Workspace context")}</p>
              </div>
            ))}
            {(knowledgeResult.sources || []).map((source, index) => (
              <div key={String(source.id || `source-${index}`)} className="rounded-lg border border-outline-variant/10 bg-surface-container-low/50 px-3 py-2">
                <p className="text-body-sm font-medium text-on-surface">{String(source.title || "Knowledge source")}</p>
                <p className="text-label-sm text-on-surface-variant/60 mt-0.5">{String(source.reference || source.content || "Workspace source")}</p>
              </div>
            ))}
          </div>
        ) : null}
        {!user && analyticsTool && analyticsResult && (
          <div className="mt-3 space-y-1.5" data-testid="copilot-analytics-results">
            {Object.entries(analyticsResult.metrics || {}).map(([key, value]) => (
              <div key={key} className="flex items-center justify-between rounded-lg border border-outline-variant/10 bg-surface-container-low/50 px-3 py-2">
                <span className="text-label-sm text-on-surface-variant/65">{key.replaceAll("_", " ")}</span>
                <span className="text-body-sm font-semibold text-on-surface">{typeof value === "object" ? JSON.stringify(value) : String(value)}</span>
              </div>
            ))}
            {(analyticsResult.campaigns || []).map((campaign, index) => (
              <div key={String(campaign.id || index)} className="rounded-lg border border-outline-variant/10 bg-surface-container-low/50 px-3 py-2">
                <p className="text-body-sm font-medium text-on-surface">{String(campaign.name || "Campaign")}</p>
                <p className="text-label-sm text-on-surface-variant/60 mt-0.5">{String(campaign.lead_count || 0)} leads</p>
              </div>
            ))}
          </div>
        )}
        {!user && message.actions && message.actions.length > 0 && <SuggestedActions actions={message.actions} onExecute={onAction} />}
      </div>
    </div>
  );
}

export default function CopilotPanel({ width = 380, variant = "sidebar" }: { width?: number; variant?: "sidebar" | "page" }) {
  const { open, setOpen, pageContext, executeAction, conversationState, groups, activeGroupId, messages, chats, activeChatId, startTask, answerClarification, newChat, switchChat } = useCopilot();
  const [chatPickerOpen, setChatPickerOpen] = useState(false);
  const chatPickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (chatPickerOpen) setChatPickerOpen(false);
      else if (open) setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [chatPickerOpen, open, setOpen]);

  useEffect(() => {
    if (!chatPickerOpen) return;
    const handler = (event: MouseEvent) => {
      if (!chatPickerRef.current?.contains(event.target as Node)) setChatPickerOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [chatPickerOpen]);

  const handleQuickReply = useCallback((option: QuickReplyOption) => startTask(option.instruction), [startTask]);
  const handleClarificationReply = useCallback((option: QuickReplyOption) => answerClarification(option.id), [answerClarification]);
  const handleAction = useCallback((action: Parameters<typeof executeAction>[0]) => { void executeAction(action); }, [executeAction]);
  const idleOptions = useMemo(() => idleQuickReplies(pageContext?.page), [pageContext?.page]);
  const working = conversationState === "working";
  const activeChat = chats.find((chat) => chat.id === activeChatId);
  const chatLabel = activeChat?.title || "New chat";

  const startNewChat = useCallback(() => {
    setChatPickerOpen(false);
    newChat();
  }, [newChat]);

  const conversationHeader = (
    <header className={`relative flex shrink-0 items-center justify-between border-b border-outline-variant/10 ${variant === "page" ? "px-6 py-3 md:px-10" : "px-4 py-3"}`}>
      <div ref={chatPickerRef} className="relative min-w-0">
        <button
          type="button"
          onClick={() => setChatPickerOpen((openState) => !openState)}
          className="flex max-w-[min(28rem,calc(100vw-7rem))] items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm font-semibold text-on-surface transition-colors hover:bg-surface-high/45"
          aria-expanded={chatPickerOpen}
          aria-haspopup="listbox"
        >
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Icon name="smart_toy" className="text-sm" />
          </span>
          <span className="truncate">{chatLabel}</span>
          <Icon name="expand_more" className={`shrink-0 text-base text-on-surface-variant/55 transition-transform ${chatPickerOpen ? "rotate-180" : ""}`} />
        </button>
        {chatPickerOpen && (
          <div className="absolute left-0 top-full z-30 mt-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-outline-variant/15 bg-surface-container-low shadow-xl shadow-black/25" role="listbox" aria-label="Copilot conversations">
            <div className="max-h-72 overflow-y-auto p-1.5">
              {chats.length === 0 ? (
                <p className="px-3 py-3 text-xs text-on-surface-variant/50">Your conversations will appear here.</p>
              ) : (
                chats.map((chat) => (
                  <button
                    key={chat.id}
                    type="button"
                    role="option"
                    aria-selected={chat.id === activeChatId}
                    onClick={() => { switchChat(chat.id); setChatPickerOpen(false); }}
                    className={`w-full truncate rounded-lg px-3 py-2.5 text-left text-sm transition-colors ${chat.id === activeChatId ? "bg-surface-high/70 text-on-surface" : "text-on-surface-variant/75 hover:bg-surface-high/45 hover:text-on-surface"}`}
                  >
                    {chat.title}
                  </button>
                ))
              )}
            </div>
            <div className="border-t border-outline-variant/10 p-1.5">
              <button type="button" onClick={startNewChat} className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm font-semibold text-on-surface-variant/80 transition-colors hover:bg-surface-high/45 hover:text-on-surface">
                <Icon name="add" className="text-base" />
                New chat
              </button>
            </div>
          </div>
        )}
      </div>
      <button type="button" onClick={startNewChat} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-on-surface-variant/60 transition-colors hover:bg-surface-high/45 hover:text-on-surface" title="New chat" aria-label="New chat">
        <Icon name="add" className="text-lg" />
      </button>
    </header>
  );

  const history = variant === "page" ? (
    <aside className="flex w-64 shrink-0 flex-col border-r border-on-surface/5 bg-surface-container-low/20">
      <div className="px-5 py-6">
        <div>
          <button type="button" onClick={newChat} className="flex w-full items-center gap-2 rounded-lg border border-on-surface/5 bg-surface-high/45 px-3 py-2 text-left text-sm font-semibold text-on-surface transition-colors hover:bg-surface-high/65" aria-label="Start new chat">
            <Icon name="add" className="text-sm" />
            Start new chat
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-5">
        <div className="mb-3 flex items-center justify-between px-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-on-surface-variant/40">
          <span>Chats</span>
          <Icon name="forum" className="text-sm" />
        </div>
        {chats.length === 0 ? (
          <p className="px-2 text-xs leading-5 text-on-surface-variant/40">Your conversations will appear here.</p>
        ) : (
          <div className="space-y-0.5">
            {chats.map((chat) => (
              <button key={chat.id} type="button" onClick={() => switchChat(chat.id)} className={`w-full rounded-lg px-3 py-2 text-left transition-colors ${chat.id === activeChatId ? "bg-surface-high/70 text-on-surface" : "text-on-surface-variant/70 hover:bg-surface-high/35 hover:text-on-surface"}`}>
                <p className="truncate text-sm font-medium">{chat.title}</p>
                <p className="mt-1 text-[10px] uppercase tracking-wider text-on-surface-variant/35">{chat.messages.length} message{chat.messages.length === 1 ? "" : "s"}</p>
              </button>
            ))}
          </div>
        )}
      </div>
    </aside>
  ) : null;

  return (
    <div className={variant === "page" ? "h-full w-full flex" : "shrink-0 h-full overflow-hidden flex justify-end bg-surface-lowest transition-[width] duration-200 ease-out"} style={variant === "page" ? undefined : { width: open ? width : 0 }} role="dialog" aria-label="Loqi AI Assistant">
      <div className={`${variant === "page" ? "w-full" : "w-[380px] max-w-[92vw] border-l border-outline-variant/15 shadow-glass"} h-full flex overflow-hidden`} style={variant === "page" ? undefined : { width }}>
        {history}
        <div className="flex-1 min-w-0 h-full flex flex-col overflow-hidden">
          {conversationHeader}
          <main className={`${variant === "page" ? "w-full max-w-5xl mx-auto px-6 md:px-12" : "w-full px-4 md:px-8"} flex-1 overflow-y-auto py-8 md:py-10`}>
            {messages.length === 0 && <div className="flex min-h-full flex-col items-center justify-center py-12 text-center"><div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary"><Icon name="smart_toy" className="text-2xl" /></div><h1 className="font-serif text-3xl tracking-tight text-on-surface">Loqi AI Assistant</h1><p className="mt-3 max-w-md text-sm leading-6 text-on-surface-variant/65">Your calm, grounded workspace for understanding leads, campaigns, drafts, replies, and outbound performance.</p><div className="mt-8 w-full max-w-3xl"><QuickReplies options={idleOptions} onSelect={handleQuickReply} variant="page" /></div></div>}
            {messages.map((message) => <MessageBubble key={message.id} message={message} onAction={handleAction} />)}
            {working && activeGroupId && <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low/50 px-3.5 py-3 text-body-sm text-on-surface-variant/70"><div className="flex items-center gap-2 text-primary mb-1"><span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />Thinking</div>{groups.find((group) => group.id === activeGroupId)?.steps.at(-1)?.text || "Working on it…"}</div>}
            {conversationState === "clarification" && <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low px-4 py-3 text-body-sm text-on-surface">{CLARIFICATION_PROMPT}</div>}
          </main>
          <div className={`${variant === "page" ? "w-full" : "w-full"} shrink-0`}>{messages.length > 0 && conversationState === "clarification" && <QuickReplies options={CLARIFICATION_REPLIES} onSelect={handleClarificationReply} variant={variant} />}<CopilotComposer onSend={startTask} disabled={working} placeholder={working ? "Loqi is working…" : "Message the AI Assistant…"} variant={variant} /></div>
        </div>
      </div>
    </div>
  );
}
