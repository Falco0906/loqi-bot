"use client";

import { useState, useCallback, useMemo } from "react";
import Icon from "../shared/Icon";

type DraftItem = {
  content: string;
  original_content: string;
  style: string;
  variant_index: number;
};

type VariantGroup = {
  style: string;
  drafts: DraftItem[];
};

type GenerationMeta = {
  generation_id: string;
  provider: string;
  model: string;
  latency_ms: number;
  token_usage: Record<string, unknown>;
  generated_at: string;
  template_used: string;
  style_used: string;
  prompt_builder_version: string;
  template_library_version: string;
  style_engine_version: string;
  context_builder_version: string;
  pipeline_version: string;
  reasoning_version: string;
};

type GenerationResult = {
  conversation_id: string;
  variants: VariantGroup[];
  metadata: GenerationMeta;
  validation_results: Array<{ severity: string; code: string; message: string; field: string }>;
};

type ReplyDraftPanelProps = {
  conversationId: string;
  sessionToken: string;
  onGenerate: (conversationId: string, styles: string[], variantCount: number) => Promise<GenerationResult | null>;
};

const STYLE_OPTIONS = [
  { id: "professional", label: "Professional", icon: "badge" },
  { id: "friendly", label: "Friendly", icon: "sentiment_satisfied" },
  { id: "executive", label: "Executive", icon: "workspace_premium" },
  { id: "technical", label: "Technical", icon: "code" },
  { id: "consultative", label: "Consultative", icon: "psychology" },
  { id: "short", label: "Short", icon: "short_text" },
  { id: "detailed", label: "Detailed", icon: "article" },
  { id: "persuasive", label: "Persuasive", icon: "trending_up" },
  { id: "neutral", label: "Neutral", icon: "balance" },
];

export default function ReplyDraftPanel({ conversationId, sessionToken, onGenerate }: ReplyDraftPanelProps) {
  const [selectedStyles, setSelectedStyles] = useState<string[]>(["professional"]);
  const [variantCount, setVariantCount] = useState(1);
  const [generation, setGeneration] = useState<GenerationResult | null>(null);
  const [activeVariant, setActiveVariant] = useState(0);
  const [activeStyle, setActiveStyle] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState("");

  const currentDraft = useMemo(() => {
    const drafts = generation?.variants[activeStyle]?.drafts;
    if (!drafts || drafts.length === 0) return null;
    return drafts[activeVariant] || drafts[0] || null;
  }, [generation, activeStyle, activeVariant]);

  const isEdited = useMemo(() => {
    if (!currentDraft) return false;
    return currentDraft.content !== currentDraft.original_content;
  }, [currentDraft]);

  const hasValidationIssues = useMemo(() => {
    return generation?.validation_results && generation.validation_results.length > 0;
  }, [generation]);

  const totalVariants = useMemo(() => {
    return generation?.variants[activeStyle]?.drafts.length ?? 0;
  }, [generation, activeStyle]);

  const handleGenerate = useCallback(async () => {
    setLoading(true);
    setError(null);
    setGeneration(null);
    setActiveVariant(0);
    setActiveStyle(0);
    setEditing(false);
    try {
      const result = await onGenerate(conversationId, selectedStyles, variantCount);
      if (result) {
        setGeneration(result);
        const first = result.variants[0]?.drafts[0];
        if (first) {
          setEditContent(first.content);
        }
      } else {
        setError("Generation returned no result.");
      }
    } catch {
      setError("Failed to generate reply.");
    } finally {
      setLoading(false);
    }
  }, [conversationId, selectedStyles, variantCount, onGenerate]);

  const handleCopy = useCallback(async () => {
    if (currentDraft?.content) {
      try {
        await navigator.clipboard.writeText(currentDraft.content);
      } catch {}
    }
  }, [currentDraft]);

  const startEditing = useCallback(() => {
    if (currentDraft) {
      setEditContent(currentDraft.content);
      setEditing(true);
    }
  }, [currentDraft]);

  const cancelEditing = useCallback(() => {
    setEditing(false);
    if (currentDraft) {
      setEditContent(currentDraft.content);
    }
  }, [currentDraft]);

  const handleRegenerate = useCallback(() => {
    if (!generation) return;
    const nextVariant = activeVariant + 1;
    const group = generation.variants[activeStyle];
    if (group && nextVariant < group.drafts.length) {
      setActiveVariant(nextVariant);
    } else if (activeStyle < generation.variants.length - 1) {
      const nextStyle = activeStyle + 1;
      setActiveStyle(nextStyle);
      setActiveVariant(0);
    } else {
      setActiveVariant(0);
    }
    setEditing(false);
  }, [generation, activeStyle, activeVariant]);

  const toggleStyle = useCallback((styleId: string) => {
    setSelectedStyles((prev) =>
      prev.includes(styleId) ? prev.filter((s) => s !== styleId) : [...prev, styleId],
    );
  }, []);

  const displayedContent = useMemo(() => {
    if (editing) return editContent;
    return currentDraft?.content || "";
  }, [editing, editContent, currentDraft]);

  return (
    <div className="rounded-xl border border-outline-variant/10 bg-charcoal/50 p-4 space-y-4">
      <h3 className="text-xs font-semibold text-on-surface-variant/70 uppercase tracking-wider">
        Reply Draft
      </h3>

      {/* Style Selector */}
      <div>
        <span className="text-[10px] text-on-surface-variant/50 uppercase tracking-wider block mb-1.5">Style</span>
        <div className="flex flex-wrap gap-1.5">
          {STYLE_OPTIONS.map((opt) => (
            <button
              key={opt.id}
              onClick={() => toggleStyle(opt.id)}
              className={`inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium transition-colors ${
                selectedStyles.includes(opt.id)
                  ? "bg-primary/20 text-primary border border-primary/30"
                  : "bg-surface-high/20 text-on-surface-variant/60 border border-outline-variant/10 hover:bg-surface-high/40"
              }`}
            >
              <Icon name={opt.icon} className="text-[10px]" />
              <span>{opt.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Variant Count */}
      <div className="flex items-center gap-3">
        <span className="text-[10px] text-on-surface-variant/50 uppercase tracking-wider">Variants</span>
        <div className="flex items-center gap-1">
          {[1, 2, 3].map((n) => (
            <button
              key={n}
              onClick={() => setVariantCount(n)}
              className={`w-6 h-6 rounded text-[11px] font-medium transition-colors ${
                variantCount === n
                  ? "bg-primary/20 text-primary"
                  : "bg-surface-high/20 text-on-surface-variant/60 hover:bg-surface-high/40"
              }`}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      {/* Generate Button */}
      <button
        onClick={handleGenerate}
        disabled={loading || selectedStyles.length === 0}
        className="w-full rounded-lg bg-primary/20 hover:bg-primary/30 text-primary text-xs font-medium px-3 py-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-2"
      >
        <Icon name={loading ? "sync" : "auto_awesome"} className={`text-sm ${loading ? "animate-spin" : ""}`} />
        <span>{loading ? "Generating..." : "Generate Reply"}</span>
      </button>

      {error && (
        <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-3 py-2">
          <p className="text-[11px] text-red-400">{error}</p>
        </div>
      )}

      {/* Draft Display */}
      {currentDraft && (
        <>
          {/* Variant Tabs */}
          {generation!.variants.length > 1 && (
            <div className="flex gap-1 border-b border-outline-variant/10 pb-2">
              {generation!.variants.map((v, i) => (
                <button
                  key={i}
                  onClick={() => { setActiveStyle(i); setActiveVariant(0); setEditing(false); }}
                  className={`text-[10px] px-2 py-1 rounded-t font-medium transition-colors ${
                    activeStyle === i
                      ? "text-primary border-b-2 border-primary"
                      : "text-on-surface-variant/50 hover:text-on-surface-variant/80"
                  }`}
                >
                  {v.style.charAt(0).toUpperCase() + v.style.slice(1)}
                </button>
              ))}
            </div>
          )}

          {/* Original indicator */}
          {isEdited && (
            <div className="flex items-center gap-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20 px-2.5 py-1.5">
              <Icon name="edit_note" className="text-[10px] text-amber-400" />
              <span className="text-[10px] text-amber-400/80">Edited from AI original</span>
              <button
                onClick={() => {
                  if (currentDraft) {
                    setEditContent(currentDraft.original_content);
                  }
                }}
                className="ml-auto text-[10px] text-amber-400/60 hover:text-amber-400 underline"
              >
                Restore original
              </button>
            </div>
          )}

          {/* Draft Content */}
          <div className="relative">
            {editing ? (
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                className="w-full min-h-[120px] rounded-lg bg-surface-high/20 border border-outline-variant/10 px-3 py-2 text-xs text-on-surface/80 font-mono leading-relaxed resize-y focus:outline-none focus:border-primary/30"
              />
            ) : (
              <div className="rounded-lg bg-surface-high/20 border border-outline-variant/10 px-3 py-2">
                <p className="text-xs text-on-surface/80 whitespace-pre-wrap leading-relaxed max-h-[200px] overflow-y-auto">
                  {displayedContent || (
                    <span className="text-on-surface-variant/40 italic">No content generated</span>
                  )}
                </p>
              </div>
            )}
          </div>

          {/* Action Buttons */}
          <div className="flex gap-2">
            <button
              onClick={handleCopy}
              className="flex-1 rounded-lg border border-outline-variant/10 px-2 py-1.5 text-[11px] text-on-surface-variant/70 hover:bg-surface-high/30 transition-colors flex items-center justify-center gap-1"
            >
              <Icon name="content_copy" className="text-[12px]" />
              <span>Copy</span>
            </button>
            {editing ? (
              <>
                <button
                  onClick={cancelEditing}
                  className="flex-1 rounded-lg border border-outline-variant/10 px-2 py-1.5 text-[11px] text-on-surface-variant/70 hover:bg-surface-high/30 transition-colors flex items-center justify-center gap-1"
                >
                  <Icon name="close" className="text-[12px]" />
                  <span>Cancel</span>
                </button>
                <button
                  onClick={() => setEditing(false)}
                  className="flex-1 rounded-lg bg-primary/20 text-primary text-[11px] font-medium px-2 py-1.5 hover:bg-primary/30 transition-colors flex items-center justify-center gap-1"
                >
                  <Icon name="check" className="text-[12px]" />
                  <span>Done</span>
                </button>
              </>
            ) : (
              <button
                onClick={startEditing}
                className="flex-1 rounded-lg border border-outline-variant/10 px-2 py-1.5 text-[11px] text-on-surface-variant/70 hover:bg-surface-high/30 transition-colors flex items-center justify-center gap-1"
              >
                <Icon name="edit" className="text-[12px]" />
                <span>Edit</span>
              </button>
            )}
            <button
              onClick={handleRegenerate}
              disabled={!generation}
              className="flex-1 rounded-lg border border-outline-variant/10 px-2 py-1.5 text-[11px] text-on-surface-variant/70 hover:bg-surface-high/30 transition-colors flex items-center justify-center gap-1 disabled:opacity-40"
            >
              <Icon name="refresh" className="text-[12px]" />
              <span>Refresh</span>
            </button>
            <button
              disabled
              className="flex-1 rounded-lg bg-primary/20 text-primary text-[11px] font-medium px-2 py-1.5 opacity-40 cursor-not-allowed flex items-center justify-center gap-1"
              title="Coming in a future phase"
            >
              <Icon name="check" className="text-[12px]" />
              <span>Approve</span>
            </button>
          </div>

          {/* Variant Counter */}
          {totalVariants > 1 && (
            <div className="flex items-center justify-center gap-2">
              <button
                onClick={() => setActiveVariant((p) => Math.max(0, p - 1))}
                disabled={activeVariant === 0}
                className="text-[10px] text-on-surface-variant/40 hover:text-on-surface-variant/70 disabled:opacity-20 transition-colors"
              >
                <Icon name="chevron_left" className="text-sm" />
              </button>
              <span className="text-[10px] text-on-surface-variant/50 tabular-nums">
                {activeVariant + 1} / {totalVariants}
              </span>
              <button
                onClick={() => setActiveVariant((p) => Math.min(totalVariants - 1, p + 1))}
                disabled={activeVariant >= totalVariants - 1}
                className="text-[10px] text-on-surface-variant/40 hover:text-on-surface-variant/70 disabled:opacity-20 transition-colors"
              >
                <Icon name="chevron_right" className="text-sm" />
              </button>
            </div>
          )}

          {/* Validation Issues */}
          {hasValidationIssues && (
            <div>
              <span className="text-[10px] text-on-surface-variant/50 uppercase tracking-wider block mb-1">Issues</span>
              <div className="space-y-0.5">
                {generation!.validation_results.slice(0, 3).map((v, i) => (
                  <div
                    key={i}
                    className={`text-[10px] px-2 py-1 rounded ${
                      v.severity === "error"
                        ? "bg-red-500/10 text-red-400"
                        : v.severity === "warning"
                          ? "bg-amber-500/10 text-amber-400"
                          : "bg-blue-500/10 text-blue-400"
                    }`}
                  >
                    {v.message}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Explainability */}
          {currentDraft.content && (
            <details className="text-[10px] text-on-surface-variant/50">
              <summary className="cursor-pointer hover:text-on-surface-variant/70">Generation info</summary>
              <div className="mt-1.5 space-y-0.5 pl-1">
                <p>Generation: {(generation!.metadata as GenerationMeta).generation_id}</p>
                <p>Provider: {(generation!.metadata as GenerationMeta).provider}</p>
                <p>Model: {(generation!.metadata as GenerationMeta).model}</p>
                <p>Template: {(generation!.metadata as GenerationMeta).template_used}</p>
                <p>Latency: {(generation!.metadata as GenerationMeta).latency_ms}ms</p>
                <p>Prompt Builder v{(generation!.metadata as GenerationMeta).prompt_builder_version}</p>
                <p>Template Library v{(generation!.metadata as GenerationMeta).template_library_version}</p>
                <p>Style Engine v{(generation!.metadata as GenerationMeta).style_engine_version}</p>
                <p>Context Builder v{(generation!.metadata as GenerationMeta).context_builder_version}</p>
                <p>Pipeline v{(generation!.metadata as GenerationMeta).pipeline_version}</p>
              </div>
            </details>
          )}
        </>
      )}

      {/* Empty State */}
      {!currentDraft && !loading && !error && (
        <div className="py-6 text-center">
          <Icon name="edit_note" className="text-xl text-on-surface-variant/30 mb-2" />
          <p className="text-[11px] text-on-surface-variant/40">
            Select a style and generate a reply draft.
          </p>
        </div>
      )}
    </div>
  );
}
