"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import WorkspaceContainer from "../../../components/layout/WorkspaceContainer";
import AppPage from "../../../components/primitives/AppPage";
import { useData } from "../../../lib/hooks/use-data";
import { fetchInbox } from "../../../lib/repositories";
import { useTellLoqi } from "../../../hooks/useTellLoqi";
import { useWorkspaceSearch } from "../../../contexts/SearchContext";
import {
  attentionTone,
  classLabel,
  classTone,
  classificationOf,
  relativeTime,
  statusLabel,
} from "../../../lib/conversation-presentation";

export default function InboxPage() {
  const router = useRouter();
  const { data, loading, error, retry } = useData(fetchInbox);
  const [search, setSearch] = useState("");
  const [classFilter, setClassFilter] = useState("all");
  const { query: sidebarQuery } = useWorkspaceSearch();

  /* Sidebar search mirrors into the inbox's own search bar */
  useEffect(() => {
    setSearch(sidebarQuery);
  }, [sidebarQuery]);

  const rows = useMemo(() => data?.rows ?? [], [data]);
  const tellLoqi = useTellLoqi("Inbox", { decisionCount: rows.length });

  /* List filtering */
  const classifications = useMemo(() => {
    const seen = new Set<string>();
    for (const r of rows) {
      const c = classificationOf(r);
      if (c) seen.add(c);
    }
    return [...seen].sort();
  }, [rows]);

  const visibleRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((r) => {
      if (classFilter !== "all" && classificationOf(r) !== classFilter) {
        return false;
      }
      if (!q) return true;
      return (
        r.name.toLowerCase().includes(q) ||
        r.company.toLowerCase().includes(q) ||
        r.preview.toLowerCase().includes(q) ||
        r.email.toLowerCase().includes(q)
      );
    });
  }, [rows, search, classFilter]);

  /* ── Loading / error states ── */

  if (loading) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="px-6 pt-6 pb-4 animate-skeleton-pulse">
            <div className="h-7 w-56 bg-surface-high/50 rounded-lg" />
            <div className="mt-3 h-9 w-full max-w-md bg-surface-high/50 rounded-lg" />
          </div>
          <div className="divide-y divide-outline-variant/5">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="px-6 py-3.5 flex items-center gap-4 animate-skeleton-pulse">
                <div className="flex-1 space-y-2">
                  <div className="h-4 w-40 bg-surface-high/50 rounded" />
                  <div className="h-3 w-72 bg-surface-high/50 rounded" />
                </div>
                <div className="h-5 w-20 bg-surface-high/50 rounded-full" />
                <div className="h-3 w-8 bg-surface-high/50 rounded" />
              </div>
            ))}
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  if (error) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="flex flex-col items-center justify-center h-full text-center">
            <p className="text-lg text-error mb-4">{error}</p>
            <button
              onClick={retry}
              className="bg-primary text-on-primary px-6 py-2 rounded-full text-sm font-medium hover:opacity-90 transition-opacity"
            >
              Retry
            </button>
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  return (
    <WorkspaceContainer>
      <div className="flex h-full flex-col min-h-0 animate-fade-in">

        {/* Header */}
        <header className="flex items-center gap-3 px-6 pt-5 pb-4 shrink-0 animate-conversation-fade">
          <span className="text-xs font-bold uppercase tracking-widest text-primary bg-primary/10 rounded-full px-3 py-1.5">
            {rows.length} conversation{rows.length !== 1 ? "s" : ""}
          </span>
        </header>

        {/* Toolbar */}
        <div className="flex items-center gap-3 px-6 pb-4 shrink-0 animate-conversation-fade">
          <div className="relative flex-1 max-w-md">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-[16px] text-on-surface-variant/40">
              search
            </span>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search conversations"
              className="w-full bg-surface-container-low/60 border border-outline-variant/10 rounded-lg pl-9 pr-3 py-2 text-sm text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:border-primary/30 transition-colors"
            />
          </div>
          <div className="relative">
            <select
              value={classFilter}
              onChange={(e) => setClassFilter(e.target.value)}
              className="appearance-none bg-surface-container-low/60 border border-outline-variant/10 rounded-lg pl-3 pr-8 py-2 text-sm text-on-surface-variant/80 focus:outline-none focus:border-primary/30 transition-colors cursor-pointer"
            >
              <option value="all">All classifications</option>
              {classifications.map((c) => (
                <option key={c} value={c}>
                  {classLabel(c)}
                </option>
              ))}
            </select>
            <span className="material-symbols-outlined absolute right-2 top-1/2 -translate-y-1/2 text-[14px] text-on-surface-variant/40 pointer-events-none">
              expand_more
            </span>
          </div>
        </div>

        {/* Dense conversation list */}
        {visibleRows.length === 0 ? (
          <div className="flex flex-col items-center justify-center flex-1 text-center px-6 animate-fade-in">
            <div className="w-12 h-12 rounded-xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-3">
              <span className="material-symbols-outlined text-2xl">inbox</span>
            </div>
            <p className="text-body-md text-on-surface-variant/70 font-medium">
              {rows.length === 0 ? "No conversations yet" : "No matching conversations"}
            </p>
            <p className="mt-1 text-body-sm text-on-surface-variant/50">
              {rows.length === 0
                ? "Conversations with your contacts appear here."
                : "Try a different search or classification filter."}
            </p>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto divide-y divide-outline-variant/5 animate-fade-in">
            {visibleRows.map((row) => {
              const classification = classificationOf(row);
              const toned = classTone(classification);
              const attention = attentionTone(classification);
              const pillLabel = classLabel(classification);
              const statusText = statusLabel(row.status);
              return (
                <button
                  key={row.id}
                  type="button"
                  onClick={() => router.push(`/conversations/${row.id}`)}
                  aria-label={`Open conversation with ${row.name}`}
                  className="w-full text-left px-6 py-3 flex items-center gap-4 transition-colors group hover:bg-surface-container/40"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2">
                      <span className="text-sm font-medium text-on-surface truncate">
                        {row.name}
                      </span>
                      <span className="text-xs text-on-surface-variant/40 truncate">
                        {row.email}
                      </span>
                      {row.company && (
                        <span className="text-xs text-on-surface-variant/50 truncate">
                          · {row.company}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-0.5 min-w-0">
                      {attention && (
                        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${attention}`} />
                      )}
                      <span className="text-xs text-on-surface-variant/60 truncate">
                        {row.preview || "No messages yet"}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    {classification && (
                      <span
                        className={`px-2 py-0.5 rounded-full text-[10px] font-medium uppercase tracking-wider ${toned}`}
                      >
                        {pillLabel}
                      </span>
                    )}
                    {statusText &&
                      statusText.toLowerCase() !== pillLabel.toLowerCase() && (
                        <span className="text-[10px] uppercase tracking-wider text-on-surface-variant/35 max-w-[120px] truncate">
                          {statusText}
                        </span>
                      )}
                    {row.messageCount > 0 && (
                      <span className="text-[11px] text-on-surface-variant/40 tabular-nums">
                        {row.messageCount}
                      </span>
                    )}
                    <span className="text-[11px] text-on-surface-variant/40 w-10 text-right tabular-nums">
                      {relativeTime(row.lastActivityAt)}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {/* Tell Loqi (slim) */}
        <div className="border-t border-outline-variant/10 px-6 py-3 shrink-0 animate-conversation-fade">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-[16px] text-on-surface-variant/40">
              auto_awesome
            </span>
            <input
              value={tellLoqi.text}
              onChange={(e) => tellLoqi.setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void tellLoqi.submit();
                }
              }}
              placeholder="Tell Loqi…"
              className="flex-1 bg-transparent text-sm text-on-surface placeholder:text-on-surface-variant/30 focus:outline-none"
            />
            <button
              type="button"
              disabled={tellLoqi.sending || !tellLoqi.text.trim()}
              onClick={() => void tellLoqi.submit()}
              className="bg-primary text-on-primary w-8 h-8 rounded-full flex items-center justify-center hover:opacity-80 transition-opacity shrink-0 disabled:opacity-40"
            >
              <span className="material-symbols-outlined text-sm">arrow_upward</span>
            </button>
          </div>
        </div>
      </div>
    </WorkspaceContainer>
  );
}
