"use client";

import { useCallback, useEffect, useMemo } from "react";
import { useCopilot, type CopilotMessage, type LeadOperationResult, type CampaignOperationResult } from "../../contexts/CopilotContext";
import QuickReplies from "./QuickReplies";
import SuggestedActions from "./SuggestedActions";
import CopilotComposer from "./CopilotComposer";
import Icon from "../shared/Icon";
import { STATE_LABELS, CLARIFICATION_PROMPT, CLARIFICATION_REPLIES, idleQuickReplies, type QuickReplyOption } from "../../lib/conversationMachine";

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
    <aside className="flex w-64 shrink-0 flex-col border-r border-outline-variant/8 bg-surface-container-low/20">
      <div className="border-b border-outline-variant/8 px-5 py-6">
        <div className="flex items-center gap-2 text-on-surface">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Icon name="smart_toy" className="text-base" />
          </span>
          <span className="font-serif text-lg tracking-tight">Loqi AI Assistant</span>
        </div>
        <div className="mt-6">
          <button type="button" onClick={newChat} className="flex w-full items-center gap-2 rounded-lg bg-primary px-3 py-2 text-left text-sm font-semibold text-on-primary transition-opacity hover:opacity-90" aria-label="Start new chat">
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
          {variant === "sidebar" && <header className="flex items-center justify-between px-4 py-3 border-b border-outline-variant/10 shrink-0"><div className="flex items-center gap-2.5"><div className="w-7 h-7 rounded-lg bg-primary/15 flex items-center justify-center"><Icon name="smart_toy" className="text-[16px] text-primary" /></div><span className="text-body-md text-on-surface font-bold">AI Assistant</span></div><div className="flex items-center gap-1.5"><span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold ${working ? "bg-primary/10 text-primary" : conversationState === "failed" ? "bg-error/10 text-error" : conversationState === "completed" ? "bg-success/10 text-success" : "bg-surface-high/60 text-on-surface-variant/60"}`}><span className={`w-1.5 h-1.5 rounded-full ${working ? "bg-primary animate-pulse" : "bg-current"}`} />{STATE_LABELS[conversationState]}</span><button type="button" onClick={newChat} className="p-1.5 rounded-lg text-on-surface-variant/50 hover:text-on-surface hover:bg-surface-high/60" title="New chat" aria-label="New chat"><Icon name="add" className="text-[18px]" /></button><button type="button" onClick={clear} className="p-1.5 rounded-lg text-on-surface-variant/50 hover:text-on-surface hover:bg-surface-high/60" title="Clear conversation" aria-label="Clear conversation"><Icon name="delete_sweep" className="text-[18px]" /></button></div></header>}
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
