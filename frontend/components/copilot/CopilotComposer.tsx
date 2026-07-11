"use client";

import { useState, useRef, useEffect } from "react";
import Icon from "../shared/Icon";

type Props = {
  onSend: (text: string) => void;
  disabled?: boolean;
};

export default function CopilotComposer({ onSend, disabled }: Props) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

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
    <form onSubmit={handleSubmit} className="border-t border-outline-variant/10 px-4 py-3">
      <div className="flex items-center gap-2 rounded-xl border border-outline-variant/20 bg-surface-lowest px-3 py-1.5 focus-within:border-primary/50 transition-colors">
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Ask Loqi..."
          disabled={disabled}
          className="flex-1 border-none bg-transparent text-body-md text-on-surface outline-none placeholder:text-on-surface-variant/40 disabled:opacity-50"
          aria-label="Ask Loqi"
        />
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          className="w-8 h-8 rounded-lg bg-primary text-on-primary flex items-center justify-center hover:brightness-110 transition-all disabled:opacity-30 shrink-0"
          aria-label="Send"
        >
          <Icon name="arrow_forward" className="text-sm" />
        </button>
      </div>
    </form>
  );
}
