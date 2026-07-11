"use client";

import { useEffect, useState, useCallback } from "react";
import {
  listDrafts,
  updateDraft,
  refineDraft,
  approveDraft,
} from "../../lib/api";
import Icon from "../shared/Icon";

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
};

export default function DraftReviewWorkspace() {
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<DraftEntry[]>([]);
  const [selectedIndex, setSelectedIndex] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [backendError, setBackendError] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editSubject, setEditSubject] = useState("");
  const [editBody, setEditBody] = useState("");
  const [refining, setRefining] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const token = (() => {
      try { return localStorage.getItem(ACTIVE_SESSION_KEY); }
      catch { return null; }
    })();
    if (token) setSessionToken(token);
  }, []);

  const fetchDrafts = useCallback(async () => {
    if (!sessionToken) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setBackendError(false);
    try {
      const res = await listDrafts(sessionToken);
      if (res.ok && Array.isArray(res.drafts)) {
        setDrafts(res.drafts as DraftEntry[]);
      }
    } catch {
      setBackendError(true);
    } finally {
      setLoading(false);
    }
  }, [sessionToken]);

  useEffect(() => {
    fetchDrafts();
  }, [fetchDrafts]);

  const selected = drafts[selectedIndex] || null;

  function handleSelect(index: number) {
    setSelectedIndex(index);
    setEditing(false);
    setMessage(null);
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
    } catch {
      setMessage("Failed to save");
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
    } catch {
      setMessage("Refinement failed");
    } finally {
      setRefining(null);
    }
  }

  async function handleApprove() {
    if (!selected || !sessionToken) return;
    try {
      const res = await approveDraft(sessionToken, selected.id);
      if (res.ok) {
        const updated = res.draft as DraftEntry;
        setDrafts((prev) =>
          prev.map((d) =>
            d.id === selected.id ? { ...d, status: updated.status } : d,
          ),
        );
        setMessage(
          updated.status === "approved" ? "Approved" : "Marked pending",
        );
      }
    } catch {
      setMessage("Failed to update");
    }
  }

  /* ── Empty: backend error ── */
  if (!loading && backendError) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6">
        <div className="w-16 h-16 rounded-2xl bg-error/10 flex items-center justify-center text-error mb-4">
          <Icon name="warning" className="text-4xl" />
        </div>
        <p className="text-body-lg text-on-surface-variant/60">
          Backend unavailable
        </p>
        <p className="mt-1 text-body-md text-on-surface-variant/40 max-w-sm">
          Could not load drafts. Make sure the backend server is running.
        </p>
        <button
          onClick={fetchDrafts}
          className="mt-4 px-5 py-2 bg-primary text-on-primary text-sm font-bold rounded-lg hover:brightness-110 transition-all"
        >
          Retry
        </button>
      </div>
    );
  }

  /* ── Empty: loading ── */
  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex items-center gap-3 text-on-surface-variant">
          <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          Loading drafts...
        </div>
      </div>
    );
  }

  /* ── Empty: no drafts ── */
  if (drafts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6">
        <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
          <Icon name="edit_note" className="text-4xl" />
        </div>
        <p className="text-body-lg text-on-surface-variant/60">No drafts yet</p>
        <p className="mt-1 text-body-md text-on-surface-variant/40 max-w-sm">
          Discover leads and use batch drafting to generate outreach drafts.
          They will appear here.
        </p>
        <a
          href="/discovery"
          className="mt-4 px-5 py-2 bg-primary text-on-primary text-sm font-bold rounded-lg hover:brightness-110 transition-all inline-flex items-center gap-2"
        >
          <Icon name="explore" className="text-sm" />
          Discover Leads
        </a>
      </div>
    );
  }

  const approvedCount = drafts.filter((d) => d.status === "approved").length;
  const needsReviewCount = drafts.filter(
    (d) => d.status === "needs_review",
  ).length;

  return (
    <div className="flex h-full overflow-hidden">
      {/* ─── Draft Queue — left panel ─── */}
      <aside className="w-72 shrink-0 border-r border-outline-variant/10 bg-surface-lowest overflow-y-auto flex flex-col">
        <div className="px-4 py-4 border-b border-outline-variant/10">
          <h2 className="text-headline-sm font-bold text-on-surface">
            Draft Queue
          </h2>
          <p className="text-xs text-on-surface-variant mt-0.5">
            {drafts.length} {drafts.length === 1 ? "draft" : "drafts"}
            {approvedCount > 0 ? ` \u00b7 ${approvedCount} approved` : ""}
            {needsReviewCount > 0
              ? ` \u00b7 ${needsReviewCount} needs review`
              : ""}
          </p>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {drafts.map((d, i) => {
            const name =
              (d.lead?.name as string) ||
              [
                d.lead?.first_name as string,
                d.lead?.last_name as string,
              ]
                .filter(Boolean)
                .join(" ") ||
              "Unknown";
            const company = (d.lead?.company as string) || "";
            const preview = d.text ? d.text.slice(0, 80).trim() : "";
            const isSelected = i === selectedIndex;
            return (
              <button
                key={d.id}
                onClick={() => handleSelect(i)}
                className={`w-full text-left rounded-lg px-3 py-2.5 transition-colors ${
                  isSelected
                    ? "bg-primary-container/20 border border-primary/20"
                    : "hover:bg-surface border border-transparent"
                }`}
              >
                <div className="flex items-start gap-2">
                  <div className="w-8 h-8 rounded-lg bg-[#1F1F23] flex items-center justify-center text-on-surface-variant/40 text-xs font-bold shrink-0 mt-0.5">
                    {name.charAt(0).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <p className="text-sm font-bold text-on-surface truncate">
                        {name}
                      </p>
                      <StatusDot status={d.status} />
                    </div>
                    {company ? (
                      <p className="text-xs text-on-surface-variant truncate">
                        {company}
                      </p>
                    ) : null}
                    {preview ? (
                      <p className="text-[11px] text-on-surface-variant/50 truncate mt-1 leading-snug">
                        {preview}
                        {d.text.length > 80 ? "..." : ""}
                      </p>
                    ) : null}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </aside>

      {/* ─── Email Editor — center panel ─── */}
      {selected ? (
        <section className="flex-1 flex flex-col overflow-hidden">
          {/* Top bar: lead info + status + approve toggle */}
          <div className="flex items-center justify-between px-6 py-3 border-b border-outline-variant/10 bg-surface-lowest/50">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-9 h-9 rounded-lg bg-[#1F1F23] flex items-center justify-center text-on-surface-variant/40 text-sm font-bold shrink-0">
                {(
                  (selected.lead?.name as string) || "U"
                ).charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0">
                <h3 className="font-bold text-on-surface text-sm truncate">
                  {(selected.lead?.name as string) || "Unknown"}
                </h3>
                <p className="text-xs text-on-surface-variant truncate">
                  {(selected.lead?.title as string) || ""}
                  {selected.lead?.company
                    ? ` \u2022 ${selected.lead.company}`
                    : ""}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <StatusBadge status={selected.status} />
              <button
                onClick={handleApprove}
                className={`px-3 py-1.5 text-xs font-bold rounded-lg border transition-colors ${
                  selected.status === "approved"
                    ? "border-outline-variant/20 text-on-surface-variant hover:border-error/40 hover:text-error"
                    : "border-secondary/30 text-secondary hover:bg-secondary/10"
                }`}
              >
                {selected.status === "approved" ? "Unapprove" : "Approve"}
              </button>
            </div>
          </div>

          {/* Toast message */}
          {message ? (
            <div className="mx-6 mt-3 rounded-lg bg-primary-container/10 border border-primary/20 px-3 py-2 text-sm text-primary">
              {message}
            </div>
          ) : null}

          {/* Editor body */}
          <div className="flex-1 overflow-y-auto px-6 py-4">
            {editing ? (
              <div className="space-y-4">
                {/* Subject field */}
                <div>
                  <label className="block text-label-md text-on-surface-variant uppercase tracking-wider mb-1">
                    Subject
                  </label>
                  <input
                    type="text"
                    value={editSubject}
                    onChange={(e) => setEditSubject(e.target.value)}
                    className="w-full rounded-xl border border-outline-variant/20 bg-surface-lowest px-4 py-2.5 text-sm text-on-surface outline-none focus:border-primary/50"
                    placeholder="Email subject line..."
                  />
                </div>
                {/* Recipient field */}
                <div>
                  <label className="block text-label-md text-on-surface-variant uppercase tracking-wider mb-1">
                    To
                  </label>
                  <input
                    type="text"
                    value={
                      ((selected.lead?.email as string) ||
                        (selected.lead?.name as string) ||
                        "") as string
                    }
                    readOnly
                    className="w-full rounded-xl border border-outline-variant/10 bg-surface-lowest/50 px-4 py-2.5 text-sm text-on-surface-variant/60 outline-none cursor-not-allowed"
                  />
                </div>
                {/* Body */}
                <div>
                  <label className="block text-label-md text-on-surface-variant uppercase tracking-wider mb-1">
                    Message
                  </label>
                  <textarea
                    value={editBody}
                    onChange={(e) => setEditBody(e.target.value)}
                    className="w-full min-h-[300px] rounded-xl border border-outline-variant/20 bg-surface-lowest p-4 text-sm text-on-surface outline-none resize-none focus:border-primary/50 leading-relaxed"
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={saveEdit}
                    className="px-5 py-2 bg-primary text-on-primary text-sm font-bold rounded-lg hover:brightness-110 transition-all"
                  >
                    Save Changes
                  </button>
                  <button
                    onClick={cancelEditing}
                    className="px-5 py-2 border border-outline-variant/20 text-on-surface text-sm font-medium rounded-lg hover:bg-surface transition-all"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-6">
                {/* Read-only subject */}
                {selected.subject ? (
                  <div>
                    <p className="text-label-md text-on-surface-variant uppercase tracking-wider mb-1">
                      Subject
                    </p>
                    <p className="text-sm font-bold text-on-surface">
                      {selected.subject}
                    </p>
                  </div>
                ) : null}
                {/* Read-only body */}
                <div
                  className="whitespace-pre-wrap text-sm text-on-surface leading-relaxed cursor-pointer"
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
              {selected.length
                ? ` \u00b7 Length: ${selected.length}`
                : ""}
            </p>
            <button
              onClick={startEditing}
              className="flex items-center gap-1.5 px-4 py-2 border border-outline-variant/20 text-on-surface text-sm font-medium rounded-lg hover:border-primary/40 hover:text-primary transition-all"
            >
              <Icon name="edit_note" className="text-base" />
              Edit
            </button>
          </div>
        </section>
      ) : null}

      {/* ─── AI Copilot + Context — right panel ─── */}
      {selected ? (
        <aside className="w-80 shrink-0 border-l border-outline-variant/10 bg-surface-lowest overflow-y-auto">
          {/* AI Copilot */}
          <div>
            <div className="px-4 py-3 border-b border-outline-variant/10">
              <h3 className="text-label-md text-on-surface-variant uppercase tracking-wider font-bold">
                AI Copilot
              </h3>
            </div>
            <div className="p-3 space-y-1">
              {[
                { key: "shorter", label: "Shorter", icon: "chevron_right" },
                { key: "longer", label: "Longer", icon: "chevron_right" },
                {
                  key: "professional",
                  label: "Professional",
                  icon: "auto_awesome",
                },
                { key: "hiring", label: "Mention Hiring", icon: "trending_up" },
                {
                  key: "expansion",
                  label: "Mention Expansion",
                  icon: "trending_up",
                },
                {
                  key: "rewrite_cta",
                  label: "Rewrite CTA",
                  icon: "edit_note",
                },
              ].map((action) => (
                <button
                  key={action.key}
                  onClick={() => handleRefine(action.key)}
                  disabled={refining === action.key}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-on-surface hover:bg-surface transition-colors disabled:opacity-50"
                >
                  <Icon
                    name={action.icon}
                    className="text-sm text-on-surface-variant shrink-0"
                  />
                  <span className="font-medium">{action.label}</span>
                  {refining === action.key ? (
                    <span className="ml-auto w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                  ) : null}
                </button>
              ))}
            </div>
          </div>

          {/* Context Panel */}
          <div className="border-t border-outline-variant/10">
            <div className="px-4 py-3">
              <h3 className="text-label-md text-on-surface-variant uppercase tracking-wider font-bold">
                Context
              </h3>
            </div>
            <div className="px-4 pb-4 space-y-4">
              {(() => {
                const c = selected.lead?.company as string | undefined;
                return c ? (
                  <ContextSection label="Company" value={c} />
                ) : null;
              })()}
              {(() => {
                const t = selected.lead?.title as string | undefined;
                return t ? (
                  <ContextSection label="Role" value={t} />
                ) : null;
              })()}
              {(() => {
                const ind = selected.lead
                  ?.company_industry as string | undefined;
                return ind ? (
                  <ContextSection label="Industry" value={ind} />
                ) : null;
              })()}

              {(() => {
                const desc = selected.lead
                  ?.company_description as string | undefined;
                return desc ? (
                  <ContextSection label="Business Summary" value={desc} />
                ) : null;
              })()}

              {selected.lead_intelligence?.recommended_pitch ? (
                <ContextSection
                  label="Messaging Angle"
                  value={
                    selected.lead_intelligence.recommended_pitch as string
                  }
                />
              ) : null}

              {(() => {
                const why = selected.lead_intelligence
                  ?.why_selected as string[] | undefined;
                if (why && why.length > 0) {
                  return (
                    <ContextSection
                      label="Why Loqi picked this lead"
                      value={why.slice(0, 2).join("; ")}
                    />
                  );
                }
                return null;
              })()}
              {(() => {
                const breakdown = selected.lead
                  ?.commercial_score_breakdown as
                  | { highlights?: string[] }
                  | undefined;
                return breakdown?.highlights &&
                  breakdown.highlights.length > 0 ? (
                  <ContextSection
                    label="Why Loqi picked this lead"
                    value={breakdown.highlights.slice(0, 2).join("; ")}
                  />
                ) : null;
              })()}

              {(() => {
                const signals = selected.lead
                  ?.buying_signals as string[] | undefined;
                return signals && signals.length > 0 ? (
                  <ContextSection
                    label="Growth Signals"
                    value={signals.slice(0, 3).join(", ")}
                  />
                ) : null;
              })()}

              {(() => {
                const events = selected.lead
                  ?.recent_events as string[] | undefined;
                return events && events.length > 0 ? (
                  <ContextSection
                    label="Recent Events"
                    value={events.slice(0, 3).join("; ")}
                  />
                ) : null;
              })()}

              {selected.lead_intelligence?.objection_risk ? (
                <ContextSection
                  label="Objection Risk"
                  value={
                    selected.lead_intelligence.objection_risk as string
                  }
                />
              ) : null}

              {(() => {
                const pp = selected.lead
                  ?.pain_points as string[] | undefined;
                return pp && pp.length > 0 ? (
                  <ContextSection
                    label="Pain Points"
                    value={pp.slice(0, 3).join(", ")}
                  />
                ) : null;
              })()}
            </div>
          </div>
        </aside>
      ) : null}
    </div>
  );
}

/* ─── Sub-components ─── */

function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    approved: "bg-secondary",
    pending: "bg-tertiary",
    needs_review: "bg-error",
  };
  return (
    <span
      className={`w-1.5 h-1.5 rounded-full shrink-0 ${
        colors[status] || "bg-on-surface-variant/40"
      }`}
      title={status}
    />
  );
}

function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    approved: "Approved",
    pending: "Pending",
    needs_review: "Needs Review",
  };
  const colors: Record<string, string> = {
    approved: "bg-secondary/10 text-secondary",
    pending: "bg-tertiary/10 text-tertiary",
    needs_review: "bg-error/10 text-error",
  };
  return (
    <span
      className={`text-xs font-bold px-2.5 py-1 rounded-full ${
        colors[status] || "bg-surface-high text-on-surface-variant"
      }`}
    >
      {labels[status] || status}
    </span>
  );
}

function ContextSection({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  if (!value || value === "\u2014") return null;
  return (
    <div>
      <p className="text-[10px] text-on-surface-variant uppercase tracking-wider mb-0.5 font-bold">
        {label}
      </p>
      <p className="text-sm text-on-surface leading-snug">{value}</p>
    </div>
  );
}
