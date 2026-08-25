"use client";

import { useState, useRef, useEffect, memo } from "react";
import Icon from "../shared/Icon";

type Props = {
  onSend: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
  variant?: "sidebar" | "page";
};

function CopilotComposer({ onSend, disabled, placeholder = "Tell Loqi what to do...", variant = "sidebar" }: Props) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!disabled) inputRef.current?.focus();
  }, [disabled]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  return (
    <form onSubmit={handleSubmit} className={`${variant === "page" ? "px-6 py-5 md:px-10 md:py-7" : "border-t border-outline-variant/10 px-4 py-3"}`}>
      <div className={`${variant === "page" ? "min-h-20 rounded-2xl bg-surface-container-low/80 px-4 py-3 shadow-lg shadow-black/10 md:px-5 md:py-4" : "rounded-xl bg-surface-lowest px-3 py-1.5"} flex items-end gap-3 border border-outline-variant/20 focus-within:border-primary/40 focus-within:ring-1 focus-within:ring-primary/20 transition-all duration-150`}>
        <textarea
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder={placeholder}
          disabled={disabled}
          rows={variant === "page" ? 2 : 1}
          className={`${variant === "page" ? "min-h-12 text-base leading-6" : "text-body-md"} max-h-40 flex-1 resize-none border-none bg-transparent text-on-surface outline-none placeholder:text-on-surface-variant/40 disabled:opacity-50`}
          aria-label="Ask AI Assistant"
        />
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          className={`${variant === "page" ? "h-10 w-10 rounded-xl" : "h-8 w-8 rounded-lg"} flex shrink-0 items-center justify-center bg-primary text-on-primary transition-all hover:brightness-110 disabled:opacity-30 active:scale-90`}
          aria-label="Send"
        >
          {disabled ? (
            <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : (
            <Icon name="arrow_forward" className="text-sm" />
          )}
        </button>
      </div>
    </form>
  );
}

export default memo(CopilotComposer);
