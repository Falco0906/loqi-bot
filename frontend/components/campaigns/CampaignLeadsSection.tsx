"use client";

import { memo, useCallback, useEffect, useState } from "react";
import { addLeadToCampaign, attachDiscoveryToCampaign, listDiscoveries } from "../../lib/api";
import { buildResearchUrl } from "../../lib/discovery-mode";
import Icon from "../shared/Icon";
import { toast } from "../shared/Toast";

type DiscoveryItem = {
  id: string;
  query: string;
  lead_count: number;
  company_count: number;
  status: string;
  score: number;
  title: string | null;
  created_at: string;
};

type Props = {
  token: string | null;
  campaignId: string;
  campaignName: string;
  leads: Array<Record<string, unknown>>;
  objective: string;
  audience: string;
  messagingAngle: string;
  /** Called after attach/add succeed so the parent can refresh in place
   * (never a full page reload). */
  onLeadsChanged?: () => void | Promise<void>;
};

const STOP_WORDS = new Set([
  "the", "a", "an", "and", "or", "for", "of", "in", "on", "to", "with", "we", "our", "your",
  "this", "that", "is", "are", "be", "will", "can", "their", "them", "they", "it", "its",
  "help", "get", "need", "wants", "who", "what", "which", "at", "by", "as", "from",
]);

function tokens(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((t) => t.length > 2 && !STOP_WORDS.has(t));
}

function rankDiscoveries(
  discoveries: Array<{
    id: string;
    query: string;
    lead_count: number;
    company_count: number;
    status: string;
    title: string | null;
    created_at: string;
  }>,
  context: string,
): DiscoveryItem[] {
  const ctxTokens = new Set(tokens(context));
  if (ctxTokens.size === 0) {
    return discoveries
      .map((d) => ({ ...d, score: 0 }))
      .sort(
        (a, b) =>
          (b.lead_count + b.company_count) - (a.lead_count + a.company_count) ||
          byRecency(a, b),
      );
  }
  return discoveries
    .map((d) => {
      const hay = `${d.title || ""} ${d.query}`;
      const hayTokens = tokens(hay);
      let overlap = 0;
      for (const t of hayTokens) {
        if (ctxTokens.has(t)) overlap += 1;
      }
      const coverage = hayTokens.length > 0 ? overlap / hayTokens.length : 0;
      const breadth = overlap / ctxTokens.size;
      const sizeBonus = Math.min(1, (d.lead_count + d.company_count) / 50);
      const score = coverage * 2 + breadth + sizeBonus * 0.5;
      return { ...d, score };
    })
    .sort((a, b) => b.score - a.score);
}

function byRecency<T extends { created_at: string }>(a: T, b: T): number {
  return String(b.created_at).localeCompare(String(a.created_at));
}

function leadName(lead: Record<string, unknown>): string {
  return String(
    lead.name || lead.full_name || lead.first_name || lead.email || "Unnamed lead",
  );
}

function leadMeta(lead: Record<string, unknown>): string {
  return [lead.title, lead.job_title, lead.company]
    .filter((v) => typeof v === "string" && v.length > 0)
    .join(" · ");
}

/**
 * Campaign Leads.
 *
 * Discovery is never auto-selected. Available discoveries are ranked against
 * the campaign context and presented with a recommendation when a genuine
 * match exists, otherwise the user is guided to research new prospects.
 */
export default memo(function CampaignLeadsSection({
  token,
  campaignId,
  campaignName,
  leads,
  objective,
  audience,
  messagingAngle,
  onLeadsChanged,
}: Props) {
  const [discoveries, setDiscoveries] = useState<DiscoveryItem[]>([]);
  const [loadingDiscoveries, setLoadingDiscoveries] = useState(false);
  const [attachingId, setAttachingId] = useState<string | null>(null);
  const [showDiscovery, setShowDiscovery] = useState(false);
  const [sortMode, setSortMode] = useState<"match" | "recent">("match");
  const [formOpen, setFormOpen] = useState(false);
  const [newLead, setNewLead] = useState({ name: "", email: "", title: "", company: "" });
  const [addBusy, setAddBusy] = useState(false);

  const researchUrl = buildResearchUrl({
    campaignId,
    campaignName,
    objective,
    audience,
    messagingAngle,
  });
  const context = [objective, audience, messagingAngle].filter(Boolean).join(" ");

  const loadDiscoveries = useCallback(async () => {
    if (!token) return;
    setLoadingDiscoveries(true);
    try {
      const res = await listDiscoveries(token);
      if (res.ok && Array.isArray(res.discoveries)) {
        const ranked = rankDiscoveries(
          (res.discoveries as Array<Record<string, unknown>>)
            .filter((d) => d.status !== "failed" && !d.archived_at)
            .map((d) => ({
              id: String(d.id),
              query: String(d.query || ""),
              lead_count: Number(d.lead_count || 0),
              company_count: Number(d.company_count || 0),
              status: String(d.status || ""),
              title: (d.title as string | null) ?? null,
              created_at: String(d.created_at || ""),
            })),
          context,
        );
        setDiscoveries(ranked);
      }
    } catch {
      /* silent */
    } finally {
      setLoadingDiscoveries(false);
    }
  }, [token, context]);

  useEffect(() => {
    if (leads.length === 0) void loadDiscoveries();
  }, [leads.length, loadDiscoveries]);

  const topMatch = discoveries[0];
  const visibleDiscoveries =
    sortMode === "recent"
      ? [...discoveries].sort(byRecency)
      : discoveries;

  async function attachDiscovery(id: string) {
    if (!token) return;
    setAttachingId(id);
    try {
      const res = await attachDiscoveryToCampaign(token, campaignId, id);
      if (!res.ok) return;
      toast("success", `${res.added} lead${res.added === 1 ? "" : "s"} attached from Discovery`);
      await onLeadsChanged?.();
    } catch {
      toast("error", "Failed to attach Discovery leads");
    } finally {
      setAttachingId(null);
    }
  }

  async function addLead() {
    if (!token) return;
    if (!newLead.email && !newLead.name) {
      toast("error", "Add at least a name or email");
      return;
    }
    setAddBusy(true);
    try {
      const res = await addLeadToCampaign(token, campaignId, { ...newLead, source: "manual" });
      if (!res.ok) return;
      toast("success", "Lead added");
      setNewLead({ name: "", email: "", title: "", company: "" });
      await onLeadsChanged?.();
    } catch {
      toast("error", "Failed to add lead");
    } finally {
      setAddBusy(false);
    }
  }

  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-outline-variant/20 pb-4">
        <div>
          <span className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium">
            Campaign Leads
          </span>
          <h4 className="text-xl font-serif text-on-surface mt-1 font-normal">
            {leads.length} lead{leads.length === 1 ? "" : "s"}
          </h4>
        </div>
        {leads.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setFormOpen((v) => !v)}
              className="rounded-lg border border-outline-variant/30 px-3 py-2 text-xs font-semibold text-on-surface hover:border-primary/50 hover:text-primary transition-all"
            >
              {formOpen ? "Cancel" : "+ Add Lead"}
            </button>
          </div>
        )}
      </div>

      {leads.length > 0 ? (
        <>
          {formOpen && (
            <div className="mt-4 p-4 rounded-xl bg-surface-lowest border border-outline-variant/20 space-y-3 animate-fade-in">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <input
                  value={newLead.name}
                  onChange={(e) => setNewLead({ ...newLead, name: e.target.value })}
                  placeholder="Full name"
                  className="rounded-lg border border-outline-variant/20 bg-surface px-3 py-2 text-sm focus:outline-none focus:border-primary/50"
                />
                <input
                  value={newLead.email}
                  onChange={(e) => setNewLead({ ...newLead, email: e.target.value })}
                  placeholder="Email"
                  type="email"
                  className="rounded-lg border border-outline-variant/20 bg-surface px-3 py-2 text-sm focus:outline-none focus:border-primary/50"
                />
                <input
                  value={newLead.title}
                  onChange={(e) => setNewLead({ ...newLead, title: e.target.value })}
                  placeholder="Title"
                  className="rounded-lg border border-outline-variant/20 bg-surface px-3 py-2 text-sm focus:outline-none focus:border-primary/50"
                />
                <input
                  value={newLead.company}
                  onChange={(e) => setNewLead({ ...newLead, company: e.target.value })}
                  placeholder="Company"
                  className="rounded-lg border border-outline-variant/20 bg-surface px-3 py-2 text-sm focus:outline-none focus:border-primary/50"
                />
              </div>
              <div className="flex justify-end">
                <button
                  onClick={() => void addLead()}
                  disabled={addBusy}
                  className="rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-on-primary hover:brightness-110 disabled:opacity-40 transition-all"
                >
                  {addBusy ? "Adding…" : "Add Lead"}
                </button>
              </div>
            </div>
          )}

          <div className="mt-4 divide-y divide-outline-variant/10 border border-outline-variant/10 rounded-xl bg-surface-lowest overflow-hidden">
            {leads.map((lead, i) => (
              <div key={i} className="flex items-center justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{leadName(lead)}</p>
                  <p className="text-xs text-on-surface-variant/60 truncate">{leadMeta(lead)}</p>
                </div>
                {typeof lead.email === "string" && lead.email ? (
                  <span className="text-xs text-on-surface-variant/50 truncate shrink-0">{lead.email}</span>
                ) : null}
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="mt-4 p-8 rounded-xl border border-dashed border-outline-variant/30 bg-surface-lowest/40 animate-fade-in">
          <p className="text-sm text-on-surface font-medium">
            Loqi needs prospects to build messaging that fits.
          </p>
          <p className="mt-1 text-xs text-on-surface-variant/60 leading-relaxed max-w-md">
            Research fresh prospects, attach a Discovery you already ran, or add a lead manually.
          </p>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <a
              href={researchUrl}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-xs font-semibold text-on-primary hover:brightness-110 transition-all"
            >
              <span className="material-symbols-outlined text-sm">travel_explore</span>
              Research prospects
            </a>
            <button
              onClick={() => setShowDiscovery((v) => !v)}
              disabled={loadingDiscoveries}
              className="inline-flex items-center gap-2 rounded-lg border border-outline-variant/30 px-4 py-2.5 text-xs font-semibold text-on-surface hover:border-primary/50 hover:text-primary transition-all disabled:opacity-40"
            >
              <span className="material-symbols-outlined text-sm">database</span>
              Attach existing Discovery
            </button>
            <button
              onClick={() => setFormOpen((v) => !v)}
              className="inline-flex items-center gap-2 rounded-lg border border-outline-variant/30 px-4 py-2.5 text-xs font-semibold text-on-surface hover:border-primary/50 hover:text-primary transition-all"
            >
              <span className="material-symbols-outlined text-sm">person_add</span>
              Add lead manually
            </button>
          </div>

          {showDiscovery && (
            <div className="mt-6 space-y-3 animate-fade-in">
              {loadingDiscoveries && discoveries.length === 0 ? (
                <div className="flex items-center gap-3 text-xs text-on-surface-variant/60">
                  <span className="w-4 h-4 border-2 border-primary/40 border-t-primary rounded-full animate-spin" />
                  Ranking discoveries against this campaign…
                </div>
              ) : discoveries.length === 0 ? (
                <div className="p-5 rounded-xl border border-outline-variant/15 bg-surface-lowest text-center">
                  <p className="text-sm text-on-surface-variant/80">No matching Discovery found.</p>
                  <a
                    href={researchUrl}
                    className="mt-3 inline-flex items-center gap-2 rounded-lg bg-secondary/15 text-secondary px-4 py-2 text-xs font-semibold hover:bg-secondary/25 transition-all"
                  >
                    <span className="material-symbols-outlined text-sm">travel_explore</span>
                    Research prospects
                  </a>
                </div>
              ) : topMatch && topMatch.score > 0.5 ? (
                <>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 text-primary px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider">
                      <span className="material-symbols-outlined text-[12px]" style={{ fontVariationSettings: "'FILL' 1" }}>
                        auto_awesome
                      </span>
                      Recommended Discovery
                    </span>
                    <SortToggle sortMode={sortMode} onChange={setSortMode} />
                  </div>
                  <DiscoveryCard
                    discovery={topMatch}
                    attaching={attachingId === topMatch.id}
                    onAttach={() => void attachDiscovery(topMatch.id)}
                    isTop
                  />
                </>
              ) : (
                <SortToggle sortMode={sortMode} onChange={setSortMode} />
              )}

              {(discoveries.length > 1 || (topMatch && topMatch.score <= 0.5)) && (
                <div>
                  {topMatch && topMatch.score > 0.5 ? (
                    <p className="text-[10px] uppercase tracking-widest text-on-surface-variant/40 font-medium mb-2">
                      Recommended Discoveries
                    </p>
                  ) : (
                    <p className="text-[10px] uppercase tracking-widest text-on-surface-variant/40 font-medium mb-2">
                      Your Discoveries
                    </p>
                  )}
                  <div className="space-y-2">
                    {visibleDiscoveries
                      .filter((d) => !(topMatch && topMatch.score > 0.5 && d.id === topMatch.id))
                      .slice(0, 4)
                      .map((d) => (
                        <DiscoveryCard
                          key={d.id}
                          discovery={d}
                          attaching={attachingId === d.id}
                          onAttach={() => void attachDiscovery(d.id)}
                        />
                      ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
});

function DiscoveryCard({
  discovery,
  attaching,
  onAttach,
  isTop,
}: {
  discovery: DiscoveryItem;
  attaching: boolean;
  onAttach: () => void;
  isTop?: boolean;
}) {
  return (
    <div
      className={`flex items-center justify-between gap-3 rounded-xl border px-4 py-3 ${
        isTop ? "border-primary/25 bg-primary-container/10" : "border-outline-variant/15 bg-surface-lowest"
      }`}
    >
      <div className="min-w-0">
        <p className="text-sm font-medium text-on-surface truncate">
          {discovery.title || discovery.query || "Untitled Discovery"}
        </p>
        <p className="text-xs text-on-surface-variant/60 truncate">
          {discovery.query}
          <span className="ml-2 text-on-surface-variant/40">
            {discovery.lead_count} lead{discovery.lead_count === 1 ? "" : "s"}
            {discovery.company_count > 0 ? ` · ${discovery.company_count} companies` : ""}
          </span>
        </p>
      </div>
      <button
        onClick={onAttach}
        disabled={attaching}
        className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-secondary px-3 py-2 text-xs font-semibold text-on-primary hover:brightness-110 disabled:opacity-40 transition-all"
      >
        {attaching ? (
          <>
            <span className="w-3 h-3 border-2 border-on-primary border-t-transparent rounded-full animate-spin" />
            Attaching…
          </>
        ) : (
          <>
            <Icon name="add_circle" className="text-sm" />
            Attach
          </>
        )}
      </button>
    </div>
  );
}

function SortToggle({
  sortMode,
  onChange,
}: {
  sortMode: "match" | "recent";
  onChange: (mode: "match" | "recent") => void;
}) {
  const option = (mode: "match" | "recent", label: string) => (
    <button
      type="button"
      onClick={() => onChange(mode)}
      className={`rounded-full px-2.5 py-1 text-[10px] uppercase tracking-wider font-semibold transition-colors ${
        sortMode === mode
          ? "bg-surface-container text-on-surface"
          : "text-on-surface-variant/50 hover:text-primary"
      }`}
    >
      {label}
    </button>
  );
  return (
    <div className="inline-flex items-center gap-0.5 rounded-full border border-outline-variant/15 bg-surface-lowest p-0.5">
      {option("match", "Best match")}
      {option("recent", "Recent")}
    </div>
  );
}
