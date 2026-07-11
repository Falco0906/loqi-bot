"use client";

import { useState } from "react";
import Icon from "../shared/Icon";

type ErrorKind =
  | "network"
  | "backend_offline"
  | "ai_provider"
  | "supabase"
  | "openai_timeout"
  | "campaign_generation"
  | "draft_generation"
  | "unknown";

const errorConfig: Record<ErrorKind, { icon: string; title: string; hint: string }> = {
  network: {
    icon: "cloud_off",
    title: "Network Error",
    hint: "Check your internet connection and try again.",
  },
  backend_offline: {
    icon: "cloud_off",
    title: "Backend Offline",
    hint: "The AI engine is not responding. Make sure the backend server is running.",
  },
  ai_provider: {
    icon: "error",
    title: "AI Provider Failed",
    hint: "The AI service returned an error. This is usually temporary.",
  },
  supabase: {
    icon: "database",
    title: "Database Error",
    hint: "The database connection failed. Data may not be saved.",
  },
  openai_timeout: {
    icon: "timer",
    title: "OpenAI Timeout",
    hint: "The AI took too long to respond. Try again in a moment.",
  },
  campaign_generation: {
    icon: "warning",
    title: "Campaign Generation Failed",
    hint: "Could not generate drafts for this campaign. Make sure it has leads assigned.",
  },
  draft_generation: {
    icon: "edit_note",
    title: "Draft Generation Failed",
    hint: "One or more drafts could not be generated. You can retry individual leads.",
  },
  unknown: {
    icon: "warning",
    title: "Unknown Error",
    hint: "Something unexpected happened.",
  },
};

type Props = {
  kind?: ErrorKind;
  message?: string;
  details?: string;
  onRetry?: () => void;
  className?: string;
};

export default function ErrorDisplay({ kind = "unknown", message, details, onRetry, className = "" }: Props) {
  const [showDetails, setShowDetails] = useState(false);
  const cfg = errorConfig[kind] || errorConfig.unknown;

  return (
    <div
      className={`rounded-xl border border-error/20 bg-error/5 px-5 py-4 ${className}`}
      role="alert"
    >
      <div className="flex items-start gap-3">
        <Icon name={cfg.icon} className="text-error text-lg mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-body-md text-on-surface font-bold">{cfg.title}</p>
          <p className="text-label-sm text-on-surface-variant/80 mt-0.5">
            {message || cfg.hint}
          </p>
          {details && (
            <>
              <button
                onClick={() => setShowDetails(!showDetails)}
                className="text-label-sm text-primary font-medium mt-2 hover:underline focus:outline-none focus:ring-2 focus:ring-primary/30 rounded"
                aria-expanded={showDetails}
              >
                {showDetails ? "Hide details" : "Show details"}
              </button>
              {showDetails && (
                <pre className="mt-2 text-xs text-on-surface-variant/60 bg-surface-high/30 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap">
                  {details}
                </pre>
              )}
            </>
          )}
        </div>
        {onRetry && (
          <button
            onClick={onRetry}
            className="shrink-0 px-4 py-2 rounded-lg bg-error/10 text-error text-sm font-bold hover:bg-error/20 transition-all focus:outline-none focus:ring-2 focus:ring-error/30"
            aria-label="Retry"
          >
            <Icon name="refresh" className="inline-block mr-1.5 text-sm" />
            Retry
          </button>
        )}
      </div>
    </div>
  );
}
