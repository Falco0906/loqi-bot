"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import AppPage from "../primitives/AppPage";
import WorkspaceContainer from "../layout/WorkspaceContainer";
import { useData } from "../../lib/hooks/use-data";
import { fetchDiscoveryList, peekCachedDiscoveryList } from "../../lib/repositories";
import { useTellLoqi } from "../../hooks/useTellLoqi";
import {
  parseDiscoveryMode,
  discoveryDetailUrl,
  startCampaignResearch,
  buildDiscoveryQuery,
} from "../../lib/discovery-mode";
import type { DiscoveryListItem } from "../../lib/domain";

function discoveryDay(createdAt: string): string {
  try {
    const created = new Date(createdAt);
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const startOfCreated = new Date(created.getFullYear(), created.getMonth(), created.getDate()).getTime();
    const dayDiff = (startOfToday - startOfCreated) / 86_400_000;
    if (dayDiff < 1) return "Today";
    if (dayDiff < 2) return "Yesterday";
    if (dayDiff < 7) return `${Math.round(dayDiff)} days ago`;
    return created.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return "Recent";
  }
}

function statusBadge(status: DiscoveryListItem["status"]) {
  switch (status) {
    case "searching":
    case "queued":
      return (
        <span className="inline-flex items-center gap-1.5 bg-surface-container px-2.5 py-1 rounded-full text-[11px] uppercase tracking-wider text-on-surface-variant font-medium">
          <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
          In progress
        </span>
      );
    case "completed":
      return (
        <span className="inline-flex items-center gap-1.5 bg-secondary-container px-2.5 py-1 rounded-full text-[11px] uppercase tracking-wider text-on-secondary-container font-medium">
          <span className="material-symbols-outlined text-xs">check</span>
          Complete
        </span>
      );
    case "failed":
    case "cancelled":
      return (
        <span className="inline-flex items-center gap-1.5 bg-error-container px-2.5 py-1 rounded-full text-[11px] uppercase tracking-wider text-on-error-container font-medium">
          <span className="material-symbols-outlined text-xs">close</span>
          Stopped
        </span>
      );
  }
}

function DiscoveryRow({ item }: { item: DiscoveryListItem }) {
  const brief = (item.summary?.brief as string) || "";
  return (
    <Link
      href={`/discovery/${item.id}`}
      className="group flex items-center justify-between gap-4 px-4 md:px-6 py-5 border-b border-outline-variant/20 transition-colors hover:bg-surface-container-low"
    >
      <div className="min-w-0 text-left">
        <p className="text-lg font-serif text-on-surface truncate group-hover:text-primary transition-colors">
          {item.query || "Untitled research"}
        </p>
        {brief && <p className="text-sm text-on-surface-variant/60 truncate mt-1">{brief}</p>}
        <p className="text-[11px] uppercase tracking-wider text-on-surface-variant/40 mt-1">
          {item.companyCount} company{item.companyCount === 1 ? "" : "ies"}
          {item.leadCount > 0 && ` · ${item.leadCount} lead${item.leadCount === 1 ? "" : "s"}`}
        </p>
      </div>
      <div className="flex items-center gap-4 shrink-0">
        {statusBadge(item.status)}
        <span className="material-symbols-outlined text-on-surface-variant/40 group-hover:text-primary transition-colors">chevron_right</span>
      </div>
    </Link>
  );
}

export default function DiscoveryHistory() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const parsed = useMemo(() => parseDiscoveryMode(searchParams), [searchParams]);
  const attachContext = parsed.mode === "campaign_attach" ? parsed.context : null;
  const attachMode = !!attachContext?.campaignId;
  const [attachAttempt, setAttachAttempt] = useState(0);
  const [attachState, setAttachState] = useState<"idle" | "starting" | "failed">("idle");
  const { data, loading, error, retry } = useData(fetchDiscoveryList, {
    initial: peekCachedDiscoveryList(),
  });
  const tellLoqi = useTellLoqi("Discovery", {});

  useEffect(() => {
    if (!attachMode || !attachContext || !attachContext.campaignId) return;
    let cancelled = false;
    const key = `loqi_attach_started_${attachContext.campaignId}`;
    setAttachState("starting");
    console.log("[kickoff] DiscoveryHistory attach effect: enter", {
      campaignId: attachContext.campaignId,
      storageKey: key,
    });
    (async () => {
      let existing = "";
      try {
        existing = sessionStorage.getItem(key) || "";
      } catch {
        existing = "";
      }
      console.log("[kickoff] DiscoveryHistory attach effect: sessionStorage read", {
        value: existing || "(empty)",
      });
      if (existing) {
        console.log(
          "[kickoff] DiscoveryHistory attach effect: REDIRECTING to stored discovery",
          existing,
          "— NO POST will be issued. Stale discovery_id may be reused forever.",
        );
        if (!cancelled) router.replace(discoveryDetailUrl(existing, attachContext));
        return;
      }
      console.log("[kickoff] DiscoveryHistory attach effect: no stored discovery — starting fresh run");
      try {
        const discoveryId = await startCampaignResearch(attachContext);
        console.log("[kickoff] DiscoveryHistory attach effect: startCampaignResearch resolved", {
          discoveryId: discoveryId || null,
        });
        if (cancelled) return;
        if (!discoveryId) {
          console.log("[kickoff] DiscoveryHistory attach effect: FAILED (no discoveryId)");
          setAttachState("failed");
          return;
        }
        try {
          sessionStorage.setItem(key, discoveryId);
          console.log("[kickoff] DiscoveryHistory attach effect: stored discoveryId", discoveryId);
        } catch {
          /* non-fatal */
        }
        router.replace(discoveryDetailUrl(discoveryId, attachContext));
        console.log("[kickoff] DiscoveryHistory attach effect: navigating to", discoveryId);
      } catch (err) {
        console.error("[kickoff] DiscoveryHistory attach effect: startCampaignResearch THREW", err);
        if (!cancelled) setAttachState("failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attachMode, attachContext, attachAttempt, router]);

  const items = data ?? [];
  const sections = [
    { label: "Today", items: items.filter((d) => discoveryDay(d.createdAt) === "Today") },
    { label: "Yesterday", items: items.filter((d) => discoveryDay(d.createdAt) === "Yesterday") },
  ];
  const older = items.filter((d) => !["Today", "Yesterday"].includes(discoveryDay(d.createdAt)));
  const hasAny = items.length > 0;

  if (attachMode && attachContext) {
    const targetLabel =
      attachContext.objective ||
      attachContext.audience ||
      attachContext.campaignName ||
      "this campaign";
    const queryLabel = buildDiscoveryQuery(attachContext);
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 flex flex-col gap-10">
            <Link
              href={`/campaigns/${encodeURIComponent(attachContext.campaignId)}`}
              className="inline-flex items-center gap-1.5 text-sm text-on-surface-variant/60 hover:text-primary transition-colors w-fit"
            >
              <span className="material-symbols-outlined text-[16px]">arrow_back</span>
              Return to campaign{attachContext.campaignName ? `: ${attachContext.campaignName}` : ""}
            </Link>
            <section className="animate-fade-in">
              <h1 className="text-4xl md:text-5xl font-serif text-on-surface leading-tight tracking-tight font-normal">
                {attachState === "failed"
                  ? "Research couldn't start"
                  : `Researching prospects for ${targetLabel}...`}
              </h1>
              <p className="text-lg text-on-surface-variant/60 leading-relaxed font-light mt-4">
                {attachState === "failed"
                  ? "The search job didn't start. Try again, or return to the campaign."
                  : queryLabel
                    ? `Looking for ${queryLabel}.`
                    : "Matching your campaign's strategy to new prospects."}
              </p>
            </section>
            <div className="flex flex-col items-center justify-center py-20 text-center animate-fade-in">
              <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
                {attachState === "failed" ? (
                  <span className="material-symbols-outlined text-3xl">error</span>
                ) : (
                  <span className="w-6 h-6 border-2 border-primary/40 border-t-primary rounded-full animate-spin" />
                )}
              </div>
              {attachState === "failed" && (
                <div className="flex gap-3">
                  <button
                    type="button"
                    onClick={() => setAttachAttempt((n) => n + 1)}
                    className="bg-primary text-on-primary px-6 py-2 rounded-full text-sm font-medium hover:opacity-90 transition-opacity"
                  >
                    Try again
                  </button>
                  <Link
                    href={`/campaigns/${encodeURIComponent(attachContext.campaignId)}`}
                    className="border border-outline-variant px-6 py-2 rounded-full text-sm font-medium text-on-surface-variant hover:text-primary transition-colors"
                  >
                    Return to campaign
                  </Link>
                </div>
              )}
            </div>
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  if (loading) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 flex flex-col gap-8">
            <div className="h-12 w-2/3 bg-surface-high/50 rounded-lg animate-skeleton-pulse" />
            <div className="bg-surface-lowest border border-outline-variant/20 rounded-xl overflow-hidden">
              {[1, 2, 3].map((i) => (
                <div key={i} className="px-6 py-6 border-b border-outline-variant/20 animate-skeleton-pulse">
                  <div className="h-5 w-1/2 bg-surface-high/50 rounded-lg mb-2" />
                  <div className="h-4 w-2/3 bg-surface-high/50 rounded-lg" />
                </div>
              ))}
            </div>
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  if (error) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 text-center">
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
      <AppPage>
        <div className="reading-column pt-16 pb-72 flex flex-col gap-10">

          <section className="animate-fade-in">
            <h1 className="text-4xl md:text-5xl font-serif text-on-surface leading-tight tracking-tight font-normal">
              Market Discovery
            </h1>
            <p className="text-lg text-on-surface-variant/60 leading-relaxed font-light mt-4">
              Every research run is saved as its own discovery. Pick one to review the companies and leads it surfaced.
            </p>
          </section>

          {hasAny ? (
            <div className="space-y-10">
              {sections.map(
                (section) =>
                  section.items.length > 0 && (
                    <section key={section.label} className="animate-fade-in">
                      <h2 className="text-[11px] uppercase tracking-widest text-on-surface-variant/60 font-semibold mb-3 px-1">
                        {section.label}
                      </h2>
                      <div className="w-full bg-surface-lowest border border-outline-variant/20 rounded-xl overflow-hidden shadow-sm">
                        {section.items.map((item) => (
                          <DiscoveryRow key={item.id} item={item} />
                        ))}
                      </div>
                    </section>
                  ),
              )}

              {older.length > 0 && (
                <section className="animate-fade-in">
                  <h2 className="text-[11px] uppercase tracking-widest text-on-surface-variant/60 font-semibold mb-3 px-1">
                    Earlier
                  </h2>
                  <div className="w-full bg-surface-lowest border border-outline-variant/20 rounded-xl overflow-hidden shadow-sm">
                    {older.slice(0, 20).map((item) => (
                      <DiscoveryRow key={item.id} item={item} />
                    ))}
                  </div>
                </section>
              )}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-20 text-center animate-fade-in">
              <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
                <span className="material-symbols-outlined text-3xl">explore</span>
              </div>
              <p className="text-body-lg text-on-surface-variant/80 font-medium">No discoveries yet</p>
              <p className="mt-1.5 text-body-md text-on-surface-variant/50 max-w-sm leading-relaxed">
                Describe your target market and Loqi will open a dedicated discovery for it.
              </p>
            </div>
          )}

        </div>
      </AppPage>

      {/* Tell Loqi — sticky footer */}
      <div
        className="fixed bottom-0 z-40 pb-6 transition-[left,right] duration-200 ease-out"
        style={{ left: "var(--sidebar-w, 16rem)", right: "var(--copilot-w, 0px)" }}
      >
        <div className="reading-column px-6">
          <div className="bg-surface-lowest border border-outline-variant/20 rounded-xl p-4 ambient-shadow">
            <label className="text-xs uppercase tracking-widest text-on-surface-variant block mb-2 px-2 font-medium">
              Tell Loqi...
            </label>
            <div className="flex items-end gap-3 px-2 pb-1">
              <textarea
                className="w-full border-none p-0 focus:ring-0 text-lg placeholder:text-on-surface-variant/30 resize-none bg-transparent outline-none"
                placeholder="Start a new discovery, e.g. 'AI startups'…"
                rows={1}
                value={tellLoqi.text}
                onChange={(e) => tellLoqi.setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void tellLoqi.submit();
                  }
                }}
              />
              <button
                type="button"
                disabled={tellLoqi.sending || !tellLoqi.text.trim()}
                onClick={() => void tellLoqi.submit()}
                className="bg-primary text-on-primary w-10 h-10 rounded-full flex items-center justify-center hover:opacity-80 transition-opacity shrink-0 disabled:opacity-40"
              >
                <span className="material-symbols-outlined text-sm">arrow_upward</span>
              </button>
            </div>
          </div>
          <div className="mt-4 flex justify-center gap-3 overflow-x-auto no-scrollbar">
            <button
              type="button"
              onClick={() => void tellLoqi.submit("Find Series A fintech companies in cross-border payments.")}
              className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
            >
              FIND SERIES A FINTECH
            </button>
            <button
              type="button"
              onClick={() => void tellLoqi.submit("Shift focus to healthcare SaaS companies.")}
              className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold"
            >
              SHIFT TO HEALTHCARE
            </button>
          </div>
        </div>
      </div>
    </WorkspaceContainer>
  );
}