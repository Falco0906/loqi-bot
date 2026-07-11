"use client";

import { useEffect, useRef } from "react";
import Icon from "../shared/Icon";
import SuggestedActions from "./SuggestedActions";
import type { CopilotMessage, CopilotAction } from "../../contexts/CopilotContext";

type Props = {
  messages: CopilotMessage[];
  sending: boolean;
  onExecuteAction: (action: CopilotAction) => void;
};

export default function ConversationHistory({
  messages,
  sending,
  onExecuteAction,
}: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  if (messages.length === 0 && !sending) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-12">
        <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center text-primary mb-4">
          <Icon name="smart_toy" className="text-2xl" />
        </div>
        <p className="text-body-md text-on-surface font-bold mb-1">Loqi OS</p>
        <p className="text-label-sm text-on-surface-variant/60 max-w-xs">
          Ask me anything about your campaigns, leads, or drafts.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
      {messages.map((msg) => (
        <div
          key={msg.id}
          className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
        >
          {msg.role === "assistant" && (
            <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
              <Icon name="smart_toy" className="text-primary text-sm" />
            </div>
          )}
          <div
            className={`max-w-[85%] rounded-2xl px-4 py-2.5 ${
              msg.role === "user"
                ? "bg-primary text-on-primary rounded-br-md"
                : "bg-surface-high/50 text-on-surface rounded-bl-md"
            }`}
          >
            <p className="text-body-sm whitespace-pre-wrap">{msg.text}</p>
            {msg.actions && msg.actions.length > 0 && (
              <div className="mt-2">
                <SuggestedActions
                  actions={msg.actions}
                  onExecute={onExecuteAction}
                />
              </div>
            )}
          </div>
        </div>
      ))}
      {sending && (
        <div className="flex gap-3">
          <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
            <Icon name="smart_toy" className="text-primary text-sm" />
          </div>
          <div className="bg-surface-high/50 rounded-2xl rounded-bl-md px-4 py-3">
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: "0ms" }} />
              <div className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: "150ms" }} />
              <div className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: "300ms" }} />
            </div>
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
