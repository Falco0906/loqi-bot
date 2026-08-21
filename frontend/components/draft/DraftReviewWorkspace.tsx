"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { ApiError, TimeoutError } from "../../lib/api";
import {
  listDrafts,
  updateDraft,
  refineDraft,
  approveDraft,
  sendDraft,
  scheduleDraft,
  cancelScheduleDraft,
  listCampaigns,
  analyzeDraft,
  askDraftQuestion,
  DraftAnalysis,
} from "../../lib/api";
import Icon from "../shared/Icon";
import { toast } from "../shared/Toast";
import { draftBucket, DraftBucket } from "../../lib/draft-lifecycle";
import { usePageContext } from "../../hooks/usePageContext";
import { useActionHandlers } from "../../hooks/useActionHandlers";
import { useWorkspaceSearch } from "../../contexts/SearchContext";

const ACTIVE_SESSION_KEY = "loqi_active_session_token";

type DraftEntry = {
  id: string;
  lead: Record<string, unknown>;
  subject?: string;
  text: string;
  status: string;
  tone?: string;
  length?: string;
  lead_intelligence?: Record<string, unknown> | null;
  company_intelligence?: Record<string, unknown> | null;
  evidence_trace?: {
    evidence_used?: string[];
    strategy_used?: string[];
    confidence?: string;
  } | null;
  campaign_id?: string;
  campaign_name?: string;
  created_at?: string;
  sent_at?: string;
};

type CampaignInfo = {
  id: string;
  name: string;
  status: string;
  lead_count: number;
  pending_drafts: number;
  approved_drafts: number;
};

type AiMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  type?: "edit_result" | "analysis" | "error";
  changes?: string[];
  analysis?: DraftAnalysis | null;
  oldText?: string;
  newText?: string;
};

type DraftEditEntry = {
  draftId: string;
  previousText: string;
  previousStatus: string;
};

function getCampaignLabel(cid: string, cmap: Map<string, string>): string {
  return cmap.get(cid) || "Uncategorized";
}

/**
 * PR-2B §5: surface WHY a critical draft action failed instead of a generic
 * message. Status-aware, never exposes backend internals or tokens.
 */
function describeDraftActionError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return "Your session expired — please refresh and sign in again.";
    if (err.status === 403) return "You don't have permission for this action.";
    if (err.status === 404) return "This draft no longer exists — refresh your draft list.";
    if (err.status === 409) return "This draft changed elsewhere — refresh and try again.";
    if (err.status === 429) return "Too many requests — wait a moment and try again.";
    if (err.status >= 500) return "The server couldn't complete this action — please retry.";
    return err.message ? `${fallback}: ${err.message}` : fallback;
  }
  if (err instanceof TimeoutError) return "The request timed out — please retry.";
  return `${fallback} (connection issue)`;
}

export default function DraftReviewWorkspace() {
  const searchParams = useSearchParams();
  const campaignParam = searchParams?.get("campaign") || null;

  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<DraftEntry[]>([]);
  const [campaigns, setCampaigns] = useState<CampaignInfo[]>([]);
  const [selectedIndex, setSelectedIndex] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [backendError, setBackendError] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editSubject, setEditSubject] = useState("");
  const [editBody, setEditBody] = useState("");
  const [refining, setRefining] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [filterCampaign, setFilterCampaign] = useState<string>(campaignParam || "__all__");
  const [filterStatus, setFilterStatus] = useState<string>("__all__");
  const [expandedCampaigns, setExpandedCampaigns] = useState<Set<string>>(new Set());

  const [aiMessages, setAiMessages] = useState<AiMessage[]>([]);
  const [aiInput, setAiInput] = useState("");
  const [aiSending, setAiSending] = useState(false);
  const [editHistory, setEditHistory] = useState<DraftEditEntry[]>([]);
  const [showDiffId, setShowDiffId] = useState<string | null>(null);
  const [highlightKey, setHighlightKey] = useState(0);
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [showSchedulePicker, setShowSchedulePicker] = useState(false);
  const [scheduleTime, setScheduleTime] = useState("");
  const [schedulingId, setSchedulingId] = useState<string | null>(null);
  const [cancellingScheduleId, setCancellingScheduleId] = useState<string | null>(null);
  const { query: searchQuery } = useWorkspaceSearch();
  const [testRecipient, setTestRecipient] = useState("");
  const aiEndRef = useRef<HTMLDivElement>(null);

  const testRecipientEnabled =
    process.env.NEXT_PUBLIC_DEV_MODE === "true" || process.env.NODE_ENV === "development";

  useEffect(() => {
    if (campaignParam) {
      setFilterCampaign(campaignParam);
      setExpandedCampaigns(new Set([campaignParam]));
    }
  }, [campaignParam]);

  usePageContext("Draft Review", {
    drafts_count: drafts.length,
    selected_index: selectedIndex,
    filter_campaign: filterCampaign,
    filter_status: filterStatus,
    selected_name: (drafts[selectedIndex]?.lead as Record<string, unknown>)?.name as string | null ?? null,
  });

  useActionHandlers({
    approve: handleApprove,
    refine: (params) => handleRefine(params?.instruction as string || "professional"),
    approve_all: async () => {
      if (!sessionToken) return;
      const pending = drafts.filter((d) => d.status === "pending");
      let campaignReady = false;
      for (const d of pending) {
        try {
          const res = await approveDraft(sessionToken, d.id);
          if (res.ok) {
            const updated = res.draft as DraftEntry;
            setDrafts((prev) =>
              prev.map((pd) =>
                pd.id === d.id ? { ...pd, status: updated.status } : pd,
              ),
            );
            if (res.current_step === "sending") campaignReady = true;
          }
        } catch { /* skip */ }
      }
      if (campaignReady) {
        setMessage(`Approved ${pending.length} drafts — campaign is ready to launch!`);
      } else {
        setMessage(`Approved ${pending.length} drafts`);
      }
    },
  });

  useEffect(() => {
    const token = (() => {
      try { return localStorage.getItem(ACTIVE_SESSION_KEY); }
      catch { return null; }
    })();
    if (token) setSessionToken(token);
  }, []);

  const fetchData = useCallback(async () => {
    if (!sessionToken) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setBackendError(false);
    try {
      const [draftRes, campaignRes] = await Promise.allSettled([
        listDrafts(sessionToken),
        listCampaigns(sessionToken),
      ]);

      if (draftRes.status === "fulfilled" && draftRes.value.ok && Array.isArray(draftRes.value.drafts)) {
        setDrafts(draftRes.value.drafts as DraftEntry[]);
      }

      if (campaignRes.status === "fulfilled" && campaignRes.value.ok && Array.isArray(campaignRes.value.campaigns)) {
        setCampaigns(campaignRes.value.campaigns as CampaignInfo[]);
      }
    } catch {
      setBackendError(true);
    } finally {
      setLoading(false);
    }
  }, [sessionToken]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const campaignMap = new Map<string, string>();
  for (const c of campaigns) {
    campaignMap.set(c.id, c.name);
  }
  for (const d of drafts) {
    const cid = d.campaign_id as string | undefined;
    if (cid && !campaignMap.has(cid)) {
      const cname = (d.campaign_name as string) || "Unknown Campaign";
      campaignMap.set(cid, cname);
    }
  }

  const draftsByCampaign = new Map<string, DraftEntry[]>();
  const q = searchQuery.trim().toLowerCase();
  const visibleDrafts = q
    ? drafts.filter((d) => {
        const leadName = ((d.lead?.name as string) || "").toLowerCase();
        const company = ((d.lead?.company as string) || "").toLowerCase();
        const email = ((d.lead?.email as string) || "").toLowerCase();
        const cid = (d.campaign_id as string) || "";
        const campaignName = (campaignMap.get(cid) || (d.campaign_name as string) || "").toLowerCase();
        return (
          leadName.includes(q) ||
          company.includes(q) ||
          email.includes(q) ||
          campaignName.includes(q)
        );
      })
    : drafts;
  for (const d of visibleDrafts) {
    const cid = (d.campaign_id as string) || "__none__";
    if (!draftsByCampaign.has(cid)) draftsByCampaign.set(cid, []);
    draftsByCampaign.get(cid)!.push(d);
  }

  const sortedCampaignIds = Array.from(draftsByCampaign.keys()).sort((a, b) => {
    const nameA = getCampaignLabel(a, campaignMap).toLowerCase();
    const nameB = getCampaignLabel(b, campaignMap).toLowerCase();
    return nameA.localeCompare(nameB);
  });

  const toggleCampaign = (cid: string) => {
    setExpandedCampaigns((prev) => {
      const next = new Set(prev);
      if (next.has(cid)) next.delete(cid);
      else next.add(cid);
      return next;
    });
  };

  const expandAll = () => {
    setExpandedCampaigns(new Set(sortedCampaignIds));
  };

  const collapseAll = () => {
    setExpandedCampaigns(new Set());
  };

  const sortedDraftsForCampaign = (drafts: DraftEntry[]): { pending: DraftEntry[]; approved: DraftEntry[]; sent: DraftEntry[] } => {
    const byBucket = (bucket: DraftBucket) =>
      drafts
        .filter((d) => draftBucket(d.status) === bucket)
        .sort((a, b) => {
          const aTime = a.sent_at || a.created_at ? new Date(a.sent_at || a.created_at || "").getTime() : 0;
          const bTime = b.sent_at || b.created_at ? new Date(b.sent_at || b.created_at || "").getTime() : 0;
          return bTime - aTime;
        });
    return { pending: byBucket("pending"), approved: byBucket("approved"), sent: byBucket("sent") };
  };

  const allSortedDrafts = (() => {
    const result: { draft: DraftEntry; campaignId: string }[] = [];
    for (const cid of sortedCampaignIds) {
      if (filterCampaign !== "__all__" && cid !== filterCampaign) continue;
      const drafts = draftsByCampaign.get(cid) || [];
      const { pending, approved, sent } = sortedDraftsForCampaign(drafts);
      for (const d of pending) result.push({ draft: d, campaignId: cid });
      for (const d of approved) result.push({ draft: d, campaignId: cid });
      for (const d of sent) result.push({ draft: d, campaignId: cid });
    }
    if (filterStatus === "pending") return result.filter((r) => draftBucket(r.draft.status) === "pending");
    if (filterStatus === "approved") return result.filter((r) => draftBucket(r.draft.status) === "approved");
    if (filterStatus === "sent") return result.filter((r) => draftBucket(r.draft.status) === "sent");
    return result;
  })();

  const globalIndexMap = new Map<string, number>();
  allSortedDrafts.forEach((item, i) => {
    globalIndexMap.set(item.draft.id, i);
  });

  const selected = allSortedDrafts[selectedIndex]?.draft || null;
  const selectedCampaignId = allSortedDrafts[selectedIndex]?.campaignId || null;
  const selectedLeadEmail = ((selected?.lead?.email as string) || "").trim();
  const noRecipientEmail = !!selected && !selectedLeadEmail;

  function handleSelectDraft(draftId: string) {
    const idx = globalIndexMap.get(draftId);
    if (idx !== undefined) {
      setSelectedIndex(idx);
      setEditing(false);
      setMessage(null);
    }
  }

  function startEditing() {
    if (!selected) return;
    setEditSubject(selected.subject || "");
    setEditBody(selected.text);
    setEditing(true);
  }

  function cancelEditing() {
    setEditing(false);
  }

  async function saveEdit() {
    if (!selected || !sessionToken) return;
    const full = editSubject
      ? `Subject: ${editSubject}\n\n${editBody}`
      : editBody;
    try {
      await updateDraft(sessionToken, selected.id, full);
      setDrafts((prev) =>
        prev.map((d) =>
          d.id === selected.id ? { ...d, subject: editSubject, text: editBody } : d,
        ),
      );
      setEditing(false);
      setMessage("Draft saved");
    } catch (err) {
      setMessage(describeDraftActionError(err, "Failed to save"));
    }
  }

  async function handleRefine(action: string) {
    if (!selected || !sessionToken) return;
    setRefining(action);
    setMessage(null);

    const instructionMap: Record<string, string> = {
      shorter: "Make this shorter and more concise",
      longer: "Make this longer with more detail",
      hiring: "Add a mention about their recent hiring activity",
      expansion: "Mention their recent company expansion or growth",
      professional: "Make this more professional and formal",
      rewrite_cta: "Rewrite the call to action to be more compelling",
    };

    try {
      const res = await refineDraft(
        sessionToken,
        selected.id,
        instructionMap[action] || action,
        selected.text,
        selected.lead,
      );
      if (res.ok) {
        const updated = res.draft as DraftEntry;
        setDrafts((prev) =>
          prev.map((d) =>
            d.id === selected.id
              ? { ...d, text: updated.text, status: updated.status }
              : d,
          ),
        );
        setMessage(`Applied: ${action}`);
      }
    } catch (err) {
      setMessage(describeDraftActionError(err, "Refinement failed"));
    } finally {
      setRefining(null);
    }
  }

  async function handleApprove() {
    if (!selected || !sessionToken) return;
    if (selected.status === "sent" || selected.status === "sending") {
      setMessage("This draft was already sent");
      return;
    }
    try {
      const res = await approveDraft(sessionToken, selected.id);
      if (res.ok) {
        const updated = res.draft as DraftEntry;
        setDrafts((prev) =>
          prev.map((d) =>
            d.id === selected.id ? { ...d, status: updated.status } : d,
          ),
        );
        if (res.current_step === "sending") {
          setMessage("Campaign ready to launch!");
        } else {
          setMessage(
            updated.status === "approved" ? "Approved" : "Marked pending",
          );
        }
      }
    } catch (err) {
      setMessage(describeDraftActionError(err, "Failed to update"));
    }
  }

  async function handleSend() {
    if (!selected || !sessionToken) return;
    if (selected.status === "sent" || selected.status === "sending") {
      setMessage("This draft was already sent");
      return;
    }
    if (selected.status !== "approved") {
      setMessage("Approve this draft before sending");
      return;
    }
    if (noRecipientEmail) {
      setMessage("This lead has no email address");
      return;
    }
    setSendingId(selected.id);
    try {
      const res = await sendDraft(
        sessionToken,
        selected.id,
        testRecipient.trim()
          ? { test_recipient: testRecipient.trim(), test_recipient_name: "Test Recipient" }
          : {},
      );
      if (res.ok) {
        setDrafts((prev) =>
          prev.map((d) =>
            d.id === selected.id ? { ...d, status: "sent" } : d,
          ),
        );
        setMessage("Draft sent successfully");
      } else {
        const err = res.error || res.send_result?.error;
        setMessage(err ? `Send failed: ${err}` : "Send failed");
      }
    } catch (err) {
      setMessage(describeDraftActionError(err, "Send request failed"));
    } finally {
      setSendingId(null);
    }
  }

  async function handleSchedule() {
    if (!selected || !sessionToken || !scheduleTime) return;
    if (noRecipientEmail) {
      setMessage("This lead has no email address");
      return;
    }
    setSchedulingId(selected.id);
    try {
      const res = await scheduleDraft(sessionToken, selected.id, new Date(scheduleTime).toISOString());
      if (res.ok) {
        setDrafts((prev) =>
          prev.map((d) =>
            d.id === selected.id ? { ...d, status: "scheduled" } : d,
          ),
        );
        setMessage(`Scheduled for ${new Date(scheduleTime).toLocaleString()}`);
        setShowSchedulePicker(false);
      } else {
        setMessage(res.error || "Schedule failed");
      }
    } catch (err) {
      setMessage(describeDraftActionError(err, "Schedule request failed"));
    } finally {
      setSchedulingId(null);
    }
  }

  async function handleCancelSchedule() {
    if (!selected || !sessionToken) return;
    setCancellingScheduleId(selected.id);
    try {
      const res = await cancelScheduleDraft(sessionToken, selected.id);
      if (res.ok) {
        setDrafts((prev) =>
          prev.map((d) =>
            d.id === selected.id ? { ...d, status: "pending" } : d,
          ),
        );
        setMessage("Schedule cancelled");
      } else {
        setMessage(res.error || "Cancel failed");
      }
    } catch {
      setMessage("Cancel request failed");
    } finally {
      setCancellingScheduleId(null);
    }
  }

  async function handleAiSend() {
    const text = aiInput.trim();
    if (!text || aiSending || !selected || !sessionToken) return;

    const userMsg: AiMessage = { id: `user-${Date.now()}`, role: "user", text };
    setAiMessages((prev) => [...prev, userMsg]);
    setAiInput("");
    setAiSending(true);

    const lead = selected.lead || {};
    const context = {
      campaign_id: selected.campaign_id,
      campaign_name: selected.campaign_name,
      company: (lead.company as string) || undefined,
      contact: (lead.name as string) || undefined,
      role: (lead.title as string) || undefined,
      industry: (lead.company_industry as string) || undefined,
      messaging_angle: (selected.lead_intelligence?.recommended_pitch as string) || undefined,
      business_summary: (lead.company_description as string) || undefined,
    };

    const intent = classifyDraftIntent(text);

    if (intent === "edit") {
      try {
        const res = await refineDraft(
          sessionToken,
          selected.id,
          text,
          selected.text,
          lead,
          context,
        );
        const rewritten = res.rewritten_text || "";
        if (rewritten) {
          const oldText = selected.text;
          const oldStatus = selected.status;
          const { summary, changes } = generateEditSummary(oldText, rewritten);
          setEditHistory((prev) => [...prev, { draftId: selected.id, previousText: oldText, previousStatus: oldStatus }]);
          setHighlightKey((k) => k + 1);
          setDrafts((prev) =>
            prev.map((d) =>
              d.id === selected.id
                ? { ...d, text: rewritten, status: "pending" }
                : d,
            ),
          );
          const msgId = `ai-${Date.now()}`;
          setAiMessages((prev) => [
            ...prev,
            { id: msgId, role: "assistant", text: `✓ Draft updated — ${summary}`, type: "edit_result", changes, oldText, newText: rewritten },
          ]);
          toast("success", "Draft updated");
        } else {
          setAiMessages((prev) => [
            ...prev,
            { id: `ai-${Date.now()}`, role: "assistant", text: "I couldn't make meaningful changes. Try a different instruction.", type: "error" },
          ]);
        }
      } catch {
        setAiMessages((prev) => [
          ...prev,
          { id: `ai-${Date.now()}`, role: "assistant", text: "Sorry, I encountered an error rewriting this draft.", type: "error" },
        ]);
      }
    } else if (intent === "question") {
      try {
        const res = await askDraftQuestion(sessionToken, text, selected.text, lead, context);
        const answer = res.answer || "I couldn't answer that right now.";
        setAiMessages((prev) => [
          ...prev,
          { id: `ai-${Date.now()}`, role: "assistant", text: answer },
        ]);
      } catch {
        setAiMessages((prev) => [
          ...prev,
          { id: `ai-${Date.now()}`, role: "assistant", text: "Sorry, I encountered an error.", type: "error" },
        ]);
      }
    } else {
      try {
        const res = await analyzeDraft(sessionToken, selected.text, lead, context);
        if (res.ok && res.analysis) {
          setAiMessages((prev) => [
            ...prev,
            { id: `ai-${Date.now()}`, role: "assistant", text: `Analysis complete`, type: "analysis", analysis: res.analysis },
          ]);
        } else {
          setAiMessages((prev) => [
            ...prev,
            { id: `ai-${Date.now()}`, role: "assistant", text: "I couldn't analyze the draft right now.", type: "error" },
          ]);
        }
      } catch {
        setAiMessages((prev) => [
          ...prev,
          { id: `ai-${Date.now()}`, role: "assistant", text: "Sorry, the analysis failed.", type: "error" },
        ]);
      }
    }

    setAiSending(false);
  }

  function handleUndo() {
    if (!selected || editHistory.length === 0) return;
    const lastEdit = [...editHistory].reverse().find((e) => e.draftId === selected.id);
    if (!lastEdit) return;
    setEditHistory((prev) => prev.filter((e) => e !== lastEdit));
    setDrafts((prev) =>
      prev.map((d) =>
        d.id === selected.id
          ? { ...d, text: lastEdit.previousText, status: lastEdit.previousStatus }
          : d,
      ),
    );
    toast("info", "Undone — previous version restored");
  }

  function handleApplyEdit(newText: string) {
    if (!selected || !sessionToken) return;
    setDrafts((prev) =>
      prev.map((d) =>
        d.id === selected.id ? { ...d, text: newText, status: "pending" } : d,
      ),
    );
    toast("success", "Draft updated");
  }

  useEffect(() => {
    aiEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [aiMessages]);

  const handleAiQuickAction = (instruction: string) => {
    setAiInput(instruction);
  };

  const hasUndo = useMemo(() => {
    if (!selected) return false;
    return editHistory.some((e) => e.draftId === selected.id);
  }, [editHistory, selected]);

  const adaptiveSuggestions = useMemo(() => {
    const suggestions: string[] = [];
    const lastMsg = aiMessages.length > 0 ? aiMessages[aiMessages.length - 1] : null;
    if (lastMsg?.type === "analysis" && lastMsg.analysis?.recommended_actions) {
      suggestions.push(...lastMsg.analysis.recommended_actions.slice(0, 3));
    }
    if (suggestions.length === 0) {
      suggestions.push("Improve personalization", "Rewrite opening", "Strengthen CTA");
    }
    return suggestions;
  }, [aiMessages]);

  const commonActions = [
    { key: "shorter", label: "Shorter" },
    { key: "longer", label: "Longer" },
    { key: "professional", label: "Professional" },
    { key: "conversational", label: "Conversational" },
  ];

  /* ── Empty: backend error ── */
  if (!loading && backendError) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6 animate-fade-in">
        <div className="w-16 h-16 rounded-2xl bg-error/10 flex items-center justify-center text-error mb-4">
          <Icon name="warning" className="text-3xl" />
        </div>
        <p className="text-body-lg text-on-surface-variant/80 font-medium">Backend unavailable</p>
        <p className="mt-1.5 text-body-md text-on-surface-variant/50 max-w-sm leading-relaxed">
          Could not load drafts. Make sure the backend server is running.
        </p>
        <button
          onClick={fetchData}
          className="mt-6 inline-flex items-center gap-1.5 rounded-lg border border-error/30 px-4 py-2 text-label-sm font-semibold text-error hover:bg-error/5 transition-all active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2"
        >
          <Icon name="refresh" className="text-sm" />
          Retry
        </button>
      </div>
    );
  }

  /* ── Empty: loading ── */
  if (loading) {
    return (
      <div className="flex h-full overflow-hidden animate-fade-in">
        <aside className="w-80 shrink-0 border-r border-outline-variant/10 bg-surface-lowest p-4 space-y-3">
          <div className="h-5 w-24 animate-skeleton-pulse bg-surface-high/50 rounded-lg" />
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-12 animate-skeleton-pulse bg-surface-high/50 rounded-lg" />
          ))}
        </aside>
        <section className="flex-1 p-6 space-y-4">
          <div className="h-4 w-48 animate-skeleton-pulse bg-surface-high/50 rounded-lg" />
          <div className="h-64 animate-skeleton-pulse bg-surface-highest/20 rounded-xl" />
        </section>
      </div>
    );
  }

  /* ── Empty: no drafts ── */
  if (drafts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6 animate-fade-in">
        <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
          <Icon name="edit_note" className="text-3xl" />
        </div>
        <p className="text-body-lg text-on-surface-variant/80 font-medium">No drafts yet</p>
        <p className="mt-1.5 text-body-md text-on-surface-variant/50 max-w-sm leading-relaxed">
          Discover leads and use batch drafting to generate outreach drafts.
          They will appear here.
        </p>
        <a
          href="/discovery"
          className="mt-6 inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-on-primary transition-all duration-150 hover:brightness-110 active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2"
        >
          <Icon name="explore" className="text-sm" />
          Discover Leads
        </a>
      </div>
    );
  }

  if (searchQuery.trim() && visibleDrafts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6 animate-fade-in">
        <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
          <Icon name="search_off" className="text-3xl" />
        </div>
        <p className="text-body-lg text-on-surface-variant/80 font-medium">No drafts match</p>
        <p className="mt-1.5 text-body-md text-on-surface-variant/50 max-w-sm leading-relaxed">
          Nothing matches &ldquo;{searchQuery.trim()}&rdquo;. Try a lead name, company, or campaign.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* ─── Draft Queue — left panel ─── */}
      <aside className="w-80 shrink-0 border-r border-outline-variant/10 bg-surface-lowest overflow-y-auto overflow-x-hidden flex flex-col">
        <div className="px-4 py-4 border-b border-outline-variant/10 min-w-0">
          <div className="flex items-center justify-between">
            <h2 className="text-headline-sm font-bold text-on-surface">Drafts</h2>
            <span className="text-xs text-on-surface-variant/50">
              {searchQuery.trim() ? `${visibleDrafts.length} of ${drafts.length}` : `${drafts.length}`} total
            </span>
          </div>

          {/* Filters */}
          <div className="mt-3 space-y-2">
            <div className="flex gap-2">
              <select
                value={filterCampaign}
                onChange={(e) => { setFilterCampaign(e.target.value); setSelectedIndex(0); }}
                className="flex-1 min-w-0 rounded-lg border border-outline-variant/20 bg-surface-low px-2.5 py-1.5 text-xs text-on-surface outline-none focus:border-primary/50"
              >
                <option value="__all__">All Campaigns</option>
                {Array.from(campaignMap.entries()).map(([cid, cname]) => (
                  <option key={cid} value={cid}>{cname}</option>
                ))}
              </select>
              <select
                value={filterStatus}
                onChange={(e) => { setFilterStatus(e.target.value); setSelectedIndex(0); }}
                className="flex-1 min-w-0 rounded-lg border border-outline-variant/20 bg-surface-low px-2.5 py-1.5 text-xs text-on-surface outline-none focus:border-primary/50"
              >
                <option value="__all__">All</option>
                <option value="pending">Pending</option>
                <option value="approved">Approved</option>
                <option value="sent">Sent</option>
              </select>
            </div>
            <div className="flex gap-2">
              <button
                onClick={expandAll}
                className="flex-1 rounded-lg border border-outline-variant/20 px-2.5 py-1.5 text-[10px] text-on-surface-variant/60 hover:text-on-surface transition-all"
              >
                Expand All
              </button>
              <button
                onClick={collapseAll}
                className="flex-1 rounded-lg border border-outline-variant/20 px-2.5 py-1.5 text-[10px] text-on-surface-variant/60 hover:text-on-surface transition-all"
              >
                Collapse All
              </button>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-2 space-y-2">
          {filterCampaign !== "__all__" ? (
            <>
              {(() => {
                const cid = filterCampaign;
                const campaignDrafts = draftsByCampaign.get(cid) || [];
                const { pending, approved, sent } = sortedDraftsForCampaign(campaignDrafts);
                const label = getCampaignLabel(cid, campaignMap);
                return (
                  <div key={cid}>
                    <div className="flex items-center gap-2 px-2 py-1.5">
                      <span className="text-xs font-bold text-on-surface truncate">{label}</span>
                      <span className="text-[10px] text-on-surface-variant/40 ml-auto">
                        {pending.length + approved.length + sent.length} drafts
                      </span>
                    </div>
                    {pending.length > 0 && (
                      <div className="mb-1">
                        <p className="px-2 py-1 text-[10px] text-on-surface-variant/40 uppercase tracking-wider font-medium">
                          Pending Review ({pending.length})
                        </p>
                        <div className="space-y-0.5">
                          {pending.map((d) => (
                            <DraftQueueItem key={d.id} draft={d} selected={d.id === selected?.id} onSelect={handleSelectDraft} />
                          ))}
                        </div>
                      </div>
                    )}
                    {approved.length > 0 && (
                      <div className="mb-1">
                        <p className="px-2 py-1 text-[10px] text-on-surface-variant/40 uppercase tracking-wider font-medium">
                          Approved ({approved.length})
                        </p>
                        <div className="space-y-0.5">
                          {approved.map((d) => (
                            <DraftQueueItem key={d.id} draft={d} selected={d.id === selected?.id} onSelect={handleSelectDraft} />
                          ))}
                        </div>
                      </div>
                    )}
                    {sent.length > 0 && (
                      <div>
                        <p className="px-2 py-1 text-[10px] text-on-surface-variant/40 uppercase tracking-wider font-medium">
                          Sent ({sent.length})
                        </p>
                        <div className="space-y-0.5">
                          {sent.map((d) => (
                            <DraftQueueItem key={d.id} draft={d} selected={d.id === selected?.id} onSelect={handleSelectDraft} />
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })()}
            </>
          ) : (
            sortedCampaignIds.map((cid) => {
              const campaignDrafts = draftsByCampaign.get(cid) || [];
              const { pending, approved, sent } = sortedDraftsForCampaign(campaignDrafts);
              const label = getCampaignLabel(cid, campaignMap);
              const isExpanded = expandedCampaigns.has(cid);
              const totalInCampaign = pending.length + approved.length + sent.length;

              return (
                <div key={cid}>
                  <button
                    onClick={() => toggleCampaign(cid)}
                    className="w-full flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-surface/60 transition-all text-left"
                  >
                    <Icon
                      name="chevron_right"
                      className={`text-sm text-on-surface-variant/40 transition-transform ${isExpanded ? "rotate-90" : ""}`}
                    />
                    <span className="text-xs font-bold text-on-surface truncate flex-1">{label}</span>
                    <span className="text-[10px] text-on-surface-variant/40">
                      {pending.length} Pending &middot; {approved.length} Approved &middot; {sent.length} Sent
                    </span>
                  </button>

                  {isExpanded && (
                    <div className="ml-2 space-y-1 mt-1 mb-2">
                      {pending.length > 0 && (
                        <div>
                          <p className="px-2 py-0.5 text-[10px] text-on-surface-variant/40 uppercase tracking-wider">
                            Pending Review
                          </p>
                          {pending.map((d) => (
                            <DraftQueueItem key={d.id} draft={d} selected={d.id === selected?.id} onSelect={handleSelectDraft} />
                          ))}
                        </div>
                      )}
                      {approved.length > 0 && (
                        <div>
                          <p className="px-2 py-0.5 text-[10px] text-on-surface-variant/40 uppercase tracking-wider">
                            Approved
                          </p>
                          {approved.map((d) => (
                            <DraftQueueItem key={d.id} draft={d} selected={d.id === selected?.id} onSelect={handleSelectDraft} />
                          ))}
                        </div>
                      )}
                      {sent.length > 0 && (
                        <div>
                          <p className="px-2 py-0.5 text-[10px] text-on-surface-variant/40 uppercase tracking-wider">
                            Sent
                          </p>
                          {sent.map((d) => (
                            <DraftQueueItem key={d.id} draft={d} selected={d.id === selected?.id} onSelect={handleSelectDraft} />
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </aside>

      {/* ─── Email Editor — center panel ─── */}
      {selected ? (
        <section className="flex-1 flex flex-col overflow-hidden">
          {/* Top bar: lead info + status + approve toggle */}
          <div className="flex items-center justify-between px-6 py-3 border-b border-outline-variant/10 bg-surface-lowest/50">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-9 h-9 rounded-lg bg-surface-container-high flex items-center justify-center text-on-surface-variant/60 text-sm font-bold shrink-0">
                {((selected.lead?.name as string) || "U").charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0">
                <h3 className="font-bold text-on-surface text-sm truncate">
                  {(selected.lead?.name as string) || "Unknown"}
                </h3>
                <p className="text-xs text-on-surface-variant truncate">
                  {(selected.lead?.title as string) || ""}
                  {selected.lead?.company ? ` \u2022 ${selected.lead.company}` : ""}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <StatusBadge status={selected.status} />
              {selected.status === "sent" && selected.sent_at ? (
                <span
                  className="text-[10px] text-on-surface-variant/40 uppercase tracking-wider"
                  title={`Sent ${new Date(selected.sent_at).toLocaleString()}`}
                >
                  Sent {new Date(selected.sent_at).toLocaleString()}
                </span>
              ) : null}
              {(selected.status === "pending" || selected.status === "needs_review" || selected.status === "approved") ? (
                <button
                  onClick={handleApprove}
                  className={`px-3 py-1.5 text-xs font-bold rounded-lg border transition-all duration-150 active:scale-[0.95] focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2 ${
                    selected.status === "approved"
                      ? "border-outline-variant/20 text-on-surface-variant hover:border-error/40 hover:text-error"
                      : "border-secondary/30 text-secondary hover:bg-secondary/10"
                  }`}
                >
                  {selected.status === "approved" ? "Unapprove" : "Approve"}
                </button>
              ) : null}
              {noRecipientEmail ? (
                <span
                  title="This lead has no email address. LinkedIn-only leads can still be researched and refined, but email can't be sent."
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg border border-warning/40 text-warning bg-warning/10"
                >
                  <Icon name="warning" className="text-xs shrink-0" />
                  This lead has no email address
                </span>
              ) : null}
              {selected.status === "approved" && !noRecipientEmail ? (
                <button
                  onClick={handleSend}
                  disabled={sendingId === selected.id}
                  className="px-3 py-1.5 text-xs font-bold rounded-lg bg-primary text-on-primary border border-primary transition-all duration-150 hover:brightness-110 active:scale-[0.95] focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2 disabled:opacity-50"
                >
                  {sendingId === selected.id ? (
                    <span className="inline-flex items-center gap-1">
                      <span className="w-2.5 h-2.5 border-2 border-on-primary border-t-transparent rounded-full animate-spin" />
                      Sending...
                    </span>
                  ) : (
                    "Send Now"
                  )}
                </button>
              ) : null}
              {selected.status === "approved" && !showSchedulePicker && !noRecipientEmail ? (
                <button
                  onClick={() => { setShowSchedulePicker(true); setScheduleTime(""); }}
                  className="px-3 py-1.5 text-xs font-bold rounded-lg border border-outline-variant/20 text-on-surface hover:border-info/40 hover:text-info transition-all duration-150 active:scale-[0.95]"
                >
                  Schedule
                </button>
              ) : null}
              {testRecipientEnabled && selected.status === "approved" ? (
                <label className="inline-flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/5 px-2.5 py-1.5">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-warning">Test recipient</span>
                  <input
                    type="email"
                    value={testRecipient}
                    onChange={(event) => setTestRecipient(event.target.value)}
                    placeholder="operator-second@gmail.com"
                    className="w-44 bg-transparent text-xs text-on-surface outline-none placeholder:text-on-surface-variant/40"
                  />
                </label>
              ) : null}
              {testRecipient.trim() ? (
                <span className="inline-flex items-center gap-1.5 rounded-lg border border-warning/40 bg-warning/10 px-3 py-1.5 text-xs font-bold text-warning">
                  <Icon name="warning" className="text-xs shrink-0" />
                  TEST RECIPIENT
                </span>
              ) : null}
              {selected.status === "scheduled" ? (
                <button
                  onClick={handleCancelSchedule}
                  disabled={cancellingScheduleId === selected.id}
                  className="px-3 py-1.5 text-xs font-bold rounded-lg border border-error/30 text-error hover:bg-error/5 transition-all duration-150 active:scale-[0.95] disabled:opacity-50"
                >
                  {cancellingScheduleId === selected.id ? "Cancelling..." : "Cancel Schedule"}
                </button>
              ) : null}
            </div>
          </div>

          {/* Toast message */}
          {message ? (
            <div className="mx-6 mt-3 rounded-lg bg-primary-container/10 border border-primary/20 px-3 py-2 text-sm text-primary animate-scale-in flex items-center gap-2">
              <Icon name="check_circle" className="text-sm shrink-0" />
              {message}
            </div>
          ) : null}

          {/* Schedule picker */}
          {showSchedulePicker && selected?.status === "approved" ? (
            <div className="mx-6 mt-3 rounded-lg bg-surface/80 border border-info/20 px-4 py-3 animate-scale-in">
              <p className="text-xs text-on-surface-variant mb-2">Schedule send time:</p>
              <div className="flex gap-2">
                <input
                  type="datetime-local"
                  value={scheduleTime}
                  onChange={(e) => setScheduleTime(e.target.value)}
                  className="flex-1 rounded-lg border border-outline-variant/20 bg-surface-low px-3 py-1.5 text-xs text-on-surface outline-none focus:border-info/50"
                />
                <button
                  onClick={handleSchedule}
                  disabled={!scheduleTime || schedulingId === selected.id}
                  className="px-3 py-1.5 text-xs font-bold rounded-lg bg-info text-on-info border border-info transition-all duration-150 hover:brightness-110 active:scale-[0.95] disabled:opacity-50"
                >
                  {schedulingId === selected.id ? (
                    <span className="inline-flex items-center gap-1">
                      <span className="w-2.5 h-2.5 border-2 border-on-info border-t-transparent rounded-full animate-spin" />
                    </span>
                  ) : "Confirm"}
                </button>
                <button
                  onClick={() => setShowSchedulePicker(false)}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg border border-outline-variant/20 text-on-surface hover:bg-surface transition-all"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : null}

          {/* Editor body */}
          <div className="flex-1 overflow-y-auto px-6 py-4">
            {editing ? (
              <div className="space-y-4">
                <div>
                  <label className="block text-label-md text-on-surface-variant uppercase tracking-wider mb-1">Subject</label>
                  <input
                    type="text"
                    value={editSubject}
                    onChange={(e) => setEditSubject(e.target.value)}
                    className="w-full rounded-xl border border-outline-variant/20 bg-surface-lowest px-4 py-2.5 text-sm text-on-surface outline-none focus:border-primary/50"
                    placeholder="Email subject line..."
                  />
                </div>
                <div>
                  <label className="block text-label-md text-on-surface-variant uppercase tracking-wider mb-1">To</label>
                  <input
                    type="text"
                    value={noRecipientEmail ? "No email address" : selectedLeadEmail}
                    readOnly
                    className={`w-full rounded-xl border border-outline-variant/10 bg-surface-lowest/50 px-4 py-2.5 text-sm outline-none cursor-not-allowed ${noRecipientEmail ? "text-error/80" : "text-on-surface-variant/60"}`}
                  />
                </div>
                <div>
                  <label className="block text-label-md text-on-surface-variant uppercase tracking-wider mb-1">Message</label>
                  <textarea
                    value={editBody}
                    onChange={(e) => setEditBody(e.target.value)}
                    className="w-full min-h-[300px] rounded-xl border border-outline-variant/20 bg-surface-lowest p-4 text-sm text-on-surface outline-none resize-none focus:border-primary/50 leading-relaxed"
                  />
                </div>
                <div className="flex gap-2">
                  <button onClick={saveEdit} className="px-5 py-2 bg-primary text-on-primary text-sm font-bold rounded-lg transition-all duration-150 hover:brightness-110 active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2">
                    Save Changes
                  </button>
                  <button onClick={cancelEditing} className="px-5 py-2 border border-outline-variant/20 text-on-surface text-sm font-medium rounded-lg transition-all duration-150 hover:bg-surface active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2">
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-6">
                {selected.subject ? (
                  <div>
                    <p className="text-label-md text-on-surface-variant uppercase tracking-wider mb-1">Subject</p>
                    <p className="text-sm font-bold text-on-surface">{selected.subject}</p>
                  </div>
                ) : null}
                <div
                  key={highlightKey}
                  className="whitespace-pre-wrap text-sm text-on-surface leading-relaxed cursor-pointer transition-all duration-500 animate-highlight-fade"
                  onClick={startEditing}
                >
                  {selected.text}
                </div>
              </div>
            )}
          </div>

          {/* Bottom bar */}
          <div className="flex items-center justify-between px-6 py-3 border-t border-outline-variant/10 bg-surface-lowest/50">
            <p className="text-xs text-on-surface-variant/50">
              {selected.tone ? `Tone: ${selected.tone}` : ""}
              {selected.length ? ` \u00b7 Length: ${selected.length}` : ""}
            </p>
            <div className="flex items-center gap-2">
              {hasUndo && (
                <button
                  onClick={handleUndo}
                  className="flex items-center gap-1.5 px-3 py-2 border border-outline-variant/20 text-on-surface text-xs font-medium rounded-lg transition-all duration-150 hover:border-error/40 hover:text-error active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2"
                >
                  <Icon name="undo" className="text-sm" />
                  Undo
                </button>
              )}
              <button
                onClick={startEditing}
                className="flex items-center gap-1.5 px-4 py-2 border border-outline-variant/20 text-on-surface text-sm font-medium rounded-lg transition-all duration-150 hover:border-primary/40 hover:text-primary active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2"
              >
                <Icon name="edit_note" className="text-base" />
                Edit
              </button>
            </div>
          </div>
        </section>
      ) : null}

      {/* ─── Inspector — right panel ─── */}
      {selected ? (
        <aside className="w-80 shrink-0 border-l border-outline-variant/10 bg-surface-lowest flex flex-col">
          {/* Context section (fixed header) */}
          <div className="shrink-0 border-b border-outline-variant/10">
            <div className="px-4 py-3">
              <h3 className="text-label-md text-on-surface-variant uppercase tracking-wider font-bold">Context</h3>
            </div>
            <div className="px-4 pb-3 space-y-2 max-h-[200px] overflow-y-auto">
              {(() => { const c = selected.lead?.company as string | undefined; return c ? <InspectorRow label="Company" value={c} /> : null; })()}
              {(() => { const t = selected.lead?.title as string | undefined; return t ? <InspectorRow label="Role" value={t} /> : null; })()}
              {(() => { const ind = selected.lead?.company_industry as string | undefined; return ind ? <InspectorRow label="Industry" value={ind} /> : null; })()}
              {(() => { const desc = selected.lead?.company_description as string | undefined; return desc ? <InspectorRow label="Business" value={desc} /> : null; })()}
              {selected.lead_intelligence?.recommended_pitch ? (
                <InspectorRow label="Messaging Angle" value={selected.lead_intelligence.recommended_pitch as string} />
              ) : null}
              {(() => {
                const signals = selected.lead?.buying_signals as string[] | undefined;
                return signals && signals.length > 0 ? <InspectorRow label="Signals" value={signals.slice(0, 3).join(", ")} /> : null;
              })()}
              {selected.lead_intelligence?.objection_risk ? (
                <InspectorRow label="Objection Risk" value={selected.lead_intelligence.objection_risk as string} />
              ) : null}
            </div>
          </div>

          {/* Evidence section — the actual company/lead evidence the draft
              was grounded on. Only observable facts are rendered; nothing is
              invented here. */}
          {(() => {
            const ci = selected.company_intelligence as Record<string, unknown> | null | undefined;
            const li = selected.lead_intelligence as Record<string, unknown> | null | undefined;
            const rows: Array<[string, unknown]> = [];
            if (ci) {
              const textish: Array<[string, keyof Record<string, unknown>]> = [
                ["Business pain", "business_pain_summary"],
                ["Technology", "technology_summary"],
                ["Growth", "growth_summary"],
                ["Buying signals", "buying_signal_summary"],
                ["Recent events", "recent_events_summary"],
                ["Qualification", "qualification_reason"],
                ["Decision context", "decision_context"],
              ];
              for (const [label, key] of textish) {
                const v = ci[key];
                if (typeof v === "string" && v.trim() && v !== "N/A") rows.push([label, v]);
              }
            }
            if (li) {
              const textish: Array<[string, keyof Record<string, unknown>]> = [
                ["Buying stage", "buying_stage"],
                ["Urgency", "urgency"],
                ["Business need", "estimated_business_need"],
                ["Best contact reason", "best_contact_reason"],
              ];
              for (const [label, key] of textish) {
                const v = li[key];
                if (typeof v === "string" && v.trim() && v !== "N/A") rows.push([label, v]);
              }
            }
            const trace = selected.evidence_trace;
            const strategyUsed =
              trace && Array.isArray(trace.strategy_used) ? trace.strategy_used : [];
            if (rows.length === 0 && strategyUsed.length === 0) return null;
            return (
              <div className="border-b border-outline-variant/10">
                <div className="px-4 py-3">
                  <h3 className="text-label-md text-on-surface-variant uppercase tracking-wider font-bold">Evidence</h3>
                </div>
                <div className="px-4 pb-3 space-y-2 max-h-[220px] overflow-y-auto">
                  {rows.map(([label, value]) => (
                    <InspectorRow key={label} label={label} value={String(value)} />
                  ))}
                  {strategyUsed.length > 0 && (
                    <InspectorRow
                      label="Playbook used"
                      value={strategyUsed.join(", ")}
                    />
                  )}
                </div>
              </div>
            );
          })()}

          {/* AI Assistant section */}
          <div className="shrink-0 border-b border-outline-variant/10">
            <div className="px-4 py-3 flex items-center justify-between">
              <h3 className="text-label-md text-on-surface-variant uppercase tracking-wider font-bold">AI Assistant</h3>
            </div>

            {/* Common quick actions (always visible) */}
            <div className="px-4 pb-1">
              <div className="flex flex-wrap gap-1.5">
                {commonActions.map((action) => (
                  <button
                    key={action.key}
                    onClick={() => handleRefine(action.key)}
                    disabled={refining === action.key}
                    className="px-2.5 py-1 rounded-lg border border-outline-variant/15 text-[10px] font-medium text-on-surface hover:bg-surface/60 transition-all disabled:opacity-50 active:scale-[0.95]"
                  >
                    {refining === action.key ? (
                      <span className="inline-flex items-center gap-1">
                        <span className="w-2.5 h-2.5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                        Applying...
                      </span>
                    ) : action.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Adaptive suggestions */}
            {adaptiveSuggestions.length > 0 && (
              <div className="px-4 pb-3">
                <p className="text-[9px] text-on-surface-variant/40 uppercase tracking-wider mb-1.5 font-medium">Suggested</p>
                <div className="flex flex-wrap gap-1.5">
                  {adaptiveSuggestions.map((s, i) => (
                    <button
                      key={i}
                      onClick={() => { setAiInput(s); }}
                      className="px-2.5 py-1 rounded-lg bg-primary-container/10 border border-primary/15 text-[10px] font-medium text-primary hover:bg-primary-container/20 transition-all active:scale-[0.95]"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Conversation (scrollable) */}
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {aiMessages.length === 0 ? (
              <p className="text-[10px] text-on-surface-variant/40 text-center py-4">
                Ask AI about this draft — try typing "make this shorter" or "mention they are hiring"
              </p>
            ) : (
              aiMessages.map((msg) => (
                <div key={msg.id} className="space-y-1">
                  {msg.role === "user" ? (
                    <div className="flex justify-end">
                      <div className="max-w-[90%] rounded-xl px-3 py-2 text-xs leading-relaxed bg-primary-container/20 text-on-surface">
                        {msg.text}
                      </div>
                    </div>
                  ) : msg.type === "edit_result" ? (
                    <div className="rounded-xl px-3 py-2 text-xs leading-relaxed bg-surface/60 text-on-surface space-y-1.5">
                      <p className="text-secondary font-semibold">{msg.text}</p>
                      {msg.changes && msg.changes.length > 0 && (
                        <ul className="space-y-0.5">
                          {msg.changes.map((c, i) => (
                            <li key={i} className="text-on-surface-variant/80 flex items-start gap-1.5">
                              <span className="text-secondary mt-0.5">•</span>
                              {c}
                            </li>
                          ))}
                        </ul>
                      )}
                      <div className="flex gap-2 pt-1">
                        {msg.oldText && msg.newText && (
                          <button
                            onClick={() => setShowDiffId(showDiffId === msg.id ? null : msg.id)}
                            className="text-[10px] font-medium text-primary hover:underline"
                          >
                            {showDiffId === msg.id ? "Hide Diff" : "Show Diff"}
                          </button>
                        )}
                        <button onClick={handleUndo} className="text-[10px] font-medium text-on-surface-variant/60 hover:text-on-surface transition-colors">
                          Undo
                        </button>
                      </div>
                      {showDiffId === msg.id && msg.oldText && msg.newText && (
                        <div className="mt-2 rounded-lg border border-outline-variant/15 overflow-hidden text-[10px] font-mono leading-relaxed">
                          {diffLines(msg.oldText, msg.newText).map((line, i) => (
                            <div
                              key={i}
                              className={`px-2 py-0.5 ${
                                line.type === "added" ? "bg-success/10 text-success" :
                                line.type === "removed" ? "bg-error/10 text-error" : "text-on-surface-variant/60"
                              }`}
                            >
                              {line.type === "added" ? "+ " : line.type === "removed" ? "- " : "  "}
                              {line.line || " "}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : msg.type === "analysis" && msg.analysis ? (
                    <div className="rounded-xl px-3 py-2.5 text-xs leading-relaxed bg-surface/60 text-on-surface space-y-2">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-on-surface">Quality</span>
                        <span className={`font-bold ${
                          msg.analysis.quality_score >= 8 ? "text-success" :
                          msg.analysis.quality_score >= 6 ? "text-tertiary" : "text-error"
                        }`}>
                          {msg.analysis.quality_score}/10
                        </span>
                      </div>
                      {msg.analysis.strengths.length > 0 && (
                        <div>
                          <p className="text-[10px] text-success uppercase tracking-wider font-medium mb-0.5">Strengths</p>
                          <ul className="space-y-0.5">
                            {msg.analysis.strengths.map((s, i) => (
                              <li key={i} className="text-on-surface-variant/80 flex items-start gap-1.5">
                                <span className="text-success mt-0.5">+</span> {s}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {msg.analysis.weaknesses.length > 0 && (
                        <div>
                          <p className="text-[10px] text-error uppercase tracking-wider font-medium mb-0.5">Weaknesses</p>
                          <ul className="space-y-0.5">
                            {msg.analysis.weaknesses.map((w, i) => (
                              <li key={i} className="text-on-surface-variant/80 flex items-start gap-1.5">
                                <span className="text-error mt-0.5">−</span> {w}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {msg.analysis.biggest_opportunity && (
                        <div>
                          <p className="text-[10px] text-primary uppercase tracking-wider font-medium mb-0.5">Biggest Opportunity</p>
                          <p className="text-on-surface-variant/90">{msg.analysis.biggest_opportunity}</p>
                        </div>
                      )}
                      {msg.analysis.estimated_reply_rate && (
                        <div className="flex items-center gap-2 pt-1 border-t border-outline-variant/10">
                          <span className="text-[10px] text-on-surface-variant/50 uppercase tracking-wider">Reply Rate</span>
                          <span className={`text-[10px] font-bold ${
                            msg.analysis.estimated_reply_rate === "Very High" ? "text-success" :
                            msg.analysis.estimated_reply_rate === "High" ? "text-secondary" :
                            msg.analysis.estimated_reply_rate === "Medium" ? "text-tertiary" : "text-error"
                          }`}>
                            {msg.analysis.estimated_reply_rate}
                          </span>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="flex justify-start">
                      <div className="max-w-[90%] rounded-xl px-3 py-2 text-xs leading-relaxed bg-surface/60 text-on-surface">
                        {msg.text}
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
            <div ref={aiEndRef} />
          </div>

          {/* Prompt box (always visible at bottom of inspector) */}
          <div className="shrink-0 border-t border-outline-variant/10 p-3">
            <div className="flex gap-2">
              <input
                type="text"
                value={aiInput}
                onChange={(e) => setAiInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleAiSend(); } }}
                placeholder="Ask AI..."
                className="flex-1 rounded-lg border border-outline-variant/20 bg-surface-low px-3 py-2 text-xs text-on-surface outline-none focus:border-primary/50 placeholder:text-on-surface-variant/30"
              />
              <button
                onClick={handleAiSend}
                disabled={aiSending || !aiInput.trim()}
                className="px-3 py-2 rounded-lg bg-primary text-on-primary text-xs font-bold transition-all duration-150 hover:brightness-110 active:scale-[0.95] disabled:opacity-50"
              >
                {aiSending ? (
                  <span className="w-3 h-3 border-2 border-on-primary border-t-transparent rounded-full animate-spin block" />
                ) : (
                  <Icon name="arrow_forward" className="text-xs" />
                )}
              </button>
            </div>
          </div>
        </aside>
      ) : null}
    </div>
  );
}

/* ─── Utility functions ─── */

function classifyDraftIntent(input: string): "edit" | "discuss" | "question" {
  const n = input.toLowerCase().trim();
  const editPatterns = [
    /^make it/i, /^rewrite/i, /^change/i, /^update/i, /^fix/i, /^tweak/i, /^shorten/i,
    /shorter/, /longer/, /casual/, /formal/, /professional/,
    /mention/, /remove/, /^add /, /improve/, /strengthen/, /rewrite/i,
    /replace/, /\btone\b/, /softer/, /stronger/, /^less /, /^more /,
    /conversational/, /friendly/, /\bcta\b/, /opening/, /close/, /jargon/,
    /personalization/, /subject/, /polish/, /clean up/i,
  ];
  for (const p of editPatterns) {
    if (p.test(n)) return "edit";
  }
  const questionPatterns = [
    /^what (is|are|does|was|were|is a|are the)/i,
    /^what's (a |an |the )?/i,
    /^how (does|do|is|can|would|should|is this different)/i,
    /^why (does|do|is|are|would|can)/i,
    /^can you explain/i,
    /^define /i,
    /^tell me about/i,
    /^what does.*mean/i,
    /^is (it|that|this) (better|worse|good|bad|correct)/i,
  ];
  for (const p of questionPatterns) {
    if (p.test(n)) return "question";
  }
  return "discuss";
}

function generateEditSummary(oldText: string, newText: string): { summary: string; changes: string[] } {
  const oldWords = oldText.split(/\s+/).filter(Boolean).length;
  const newWords = newText.split(/\s+/).filter(Boolean).length;
  const pct = oldWords > 0 ? Math.round(((newWords - oldWords) / oldWords) * 100) : 0;
  const changes: string[] = [];

  if (Math.abs(pct) >= 3) {
    changes.push(`${pct > 0 ? "Extended" : "Shortened"} by ${Math.abs(pct)}%`);
  } else {
    changes.push("Similar length");
  }

  const oldLower = oldText.toLowerCase();
  const newLower = newText.toLowerCase();

  const casualWords = ["hey", "hi", "just", "thought", "wanted", "checking"];
  const formalWords = ["dear", "sincerely", "regards", "opportunity", "pleasure"];
  const oldCasual = casualWords.filter((w) => oldLower.includes(w)).length;
  const newCasual = casualWords.filter((w) => newLower.includes(w)).length;
  if (newCasual > oldCasual) changes.push("More conversational tone");
  else if (newCasual < oldCasual) changes.push("More formal tone");

  const oldFormal = formalWords.filter((w) => oldLower.includes(w)).length;
  const newFormal = formalWords.filter((w) => newLower.includes(w)).length;
  if (newFormal > oldFormal) changes.push("More formal tone");
  else if (newFormal < oldFormal && newCasual <= oldCasual) changes.push("Less formal tone");

  if (oldLower.includes("you") && !newLower.includes("you")) changes.push("Less direct personalization");
  if (!oldLower.includes("you") && newLower.includes("you")) changes.push("More direct personalization");

  const ctaWords = ["meet", "chat", "talk", "call", "discuss", "book", "schedule", "reply", " let "];
  const oldCta = ctaWords.some((w) => oldLower.includes(w));
  const newCta = ctaWords.some((w) => newLower.includes(w));
  if (!oldCta && newCta) changes.push("Added CTA");
  else if (oldCta && !newCta) changes.push("Removed CTA");

  return {
    summary: pct <= -5 ? "Shortened draft" : pct >= 5 ? "Extended draft" : "Updated draft",
    changes: changes.length > 0 ? changes : ["Refined messaging"],
  };
}

function diffLines(oldText: string, newText: string): { type: "same" | "added" | "removed"; line: string }[] {
  const oldLines = oldText.split("\n");
  const newLines = newText.split("\n");
  const result: { type: "same" | "added" | "removed"; line: string }[] = [];
  const maxLen = Math.max(oldLines.length, newLines.length);
  for (let i = 0; i < maxLen; i++) {
    if (i < oldLines.length && i < newLines.length) {
      if (oldLines[i] === newLines[i]) {
        result.push({ type: "same", line: oldLines[i] });
      } else {
        result.push({ type: "removed", line: oldLines[i] });
        result.push({ type: "added", line: newLines[i] });
      }
    } else if (i < oldLines.length) {
      result.push({ type: "removed", line: oldLines[i] });
    } else {
      result.push({ type: "added", line: newLines[i] });
    }
  }
  return result;
}

/* ─── Sub-components ─── */

function DraftQueueItem({ draft, selected, onSelect }: { draft: DraftEntry; selected: boolean; onSelect: (id: string) => void }) {
  const name =
    (draft.lead?.name as string) ||
    [draft.lead?.first_name as string, draft.lead?.last_name as string].filter(Boolean).join(" ") ||
    "Unknown";
  const company = (draft.lead?.company as string) || "";
  const email = ((draft.lead?.email as string) || "").trim();
  const preview = draft.text ? draft.text.slice(0, 70).trim() : "";
  return (
    <button
      onClick={() => onSelect(draft.id)}
      className={`w-full text-left rounded-lg px-2.5 py-2 transition-all duration-100 focus-visible:outline-2 focus-visible:outline-primary/60 focus-visible:outline-offset-2 ${
        selected
          ? "bg-primary-container/20 border border-primary/20"
          : "hover:bg-surface/60 border border-transparent"
      }`}
    >
      <div className="flex items-start gap-2">
        <div className="w-7 h-7 rounded-lg bg-surface-container-high flex items-center justify-center text-on-surface-variant/60 text-[10px] font-bold shrink-0 mt-0.5">
          {name.charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <p className="text-xs font-bold text-on-surface truncate">{name}</p>
            {!email ? (
              <span title="This lead has no email address — email can't be sent">
                <Icon name="warning" className="text-[10px] text-warning shrink-0" />
              </span>
            ) : null}
            <StatusDot status={draft.status} />
          </div>
          {company ? <p className="text-[10px] text-on-surface-variant truncate">{company}</p> : null}
          {preview ? (
            <p className="text-[10px] text-on-surface-variant/50 truncate mt-0.5 leading-snug">{preview}{draft.text.length > 70 ? "..." : ""}</p>
          ) : null}
        </div>
      </div>
    </button>
  );
}

function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    approved: "bg-secondary",
    pending: "bg-tertiary",
    needs_review: "bg-error",
    sent: "bg-primary",
    scheduled: "bg-info",
  };
  return <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${colors[status] || "bg-on-surface-variant/40"}`} title={status} />;
}

function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = { approved: "Approved", pending: "Pending", needs_review: "Needs Review", sent: "Sent", scheduled: "Scheduled" };
  const colors: Record<string, string> = {
    approved: "bg-secondary/10 text-secondary",
    pending: "bg-tertiary/10 text-tertiary",
    needs_review: "bg-error/10 text-error",
    sent: "bg-primary/10 text-primary",
    scheduled: "bg-info/10 text-info",
  };
  return (
    <span className={`text-xs font-bold px-2.5 py-1 rounded-full ${colors[status] || "bg-surface-high text-on-surface-variant"}`}>
      {labels[status] || status}
    </span>
  );
}

function InspectorRow({ label, value }: { label: string; value: string }) {
  if (!value || value === "\u2014") return null;
  return (
    <div className="flex items-start gap-2">
      <p className="text-[10px] text-on-surface-variant/50 uppercase tracking-wider font-medium shrink-0 w-20 leading-snug pt-0.5">{label}</p>
      <p className="text-xs text-on-surface leading-snug">{value}</p>
    </div>
  );
}
