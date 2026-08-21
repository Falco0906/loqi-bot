"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import WorkspaceContainer from "../../../components/layout/WorkspaceContainer";
import AppPage from "../../../components/primitives/AppPage";
import EmptyState from "../../../components/shared/EmptyState";
import Icon from "../../../components/shared/Icon";
import { toast } from "../../../components/shared/Toast";
import { usePageContext } from "../../../hooks/usePageContext";
import {
  archiveStrategicUpdate,
  approveStrategicAction,
  dismissStrategicAction,
  executeStrategicAction,
  listStrategicUpdates,
  listStrategicActions,
  proposeStrategicAction,
  refineStrategicAction,
  refreshStrategicUpdates,
  type StrategicEvidence,
  type StrategicAction,
  type StrategicUpdate,
} from "../../../lib/api";

const ACTIVE_SESSION_KEY = "loqi_active_session_token";

function dateLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown date";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function label(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function evidenceTitle(evidence: StrategicEvidence): string {
  if (evidence.message_id) return `Message ${evidence.message_id.slice(0, 12)}`;
  if (evidence.conversation_id) return `Conversation ${evidence.conversation_id.slice(0, 12)}`;
  if (evidence.campaign_id) return `Campaign ${evidence.campaign_id.slice(0, 12)}`;
  return `${label(evidence.entity_type)} ${evidence.entity_id.slice(0, 12)}`;
}

function evidenceHref(evidence: StrategicEvidence): string | null {
  if (evidence.conversation_id) return `/conversations/${evidence.conversation_id}`;
  if (evidence.campaign_id) return `/campaigns/${evidence.campaign_id}`;
  return null;
}

function EvidenceList({ evidence }: { evidence: StrategicEvidence[] }) {
  if (evidence.length === 0) {
    return <p className="text-xs text-on-surface-variant/50">No structured evidence references were retained.</p>;
  }
  return (
    <div className="space-y-2">
      {evidence.map((reference) => {
        const href = evidenceHref(reference);
        const content = (
          <div className="flex items-start justify-between gap-4 rounded-lg border border-outline-variant/10 bg-surface-lowest px-3 py-2.5">
            <div className="min-w-0">
              <p className="text-xs font-semibold text-on-surface">{evidenceTitle(reference)}</p>
              <p className="mt-1 text-[11px] text-on-surface-variant/60">
                {label(reference.signal_type)} · {dateLabel(reference.observed_at)}
                {reference.value ? ` · ${String(reference.value)}` : ""}
              </p>
            </div>
            {href && <Icon name="arrow_forward" className="mt-0.5 shrink-0 text-sm text-primary" />}
          </div>
        );
        return href ? <a key={reference.signal_id} href={href} className="block hover:opacity-80">{content}</a> : <div key={reference.signal_id}>{content}</div>;
      })}
    </div>
  );
}

function actionTypesForUpdate(updateType: string): string[] {
  if (updateType === "messaging") return ["update_messaging"];
  if (updateType === "icp") return ["refine_icp"];
  if (["performance", "campaign", "follow_up", "opportunity"].includes(updateType)) return ["create_campaign"];
  return [];
}

function ActionSection({
  update,
  actions,
  selectedActionId,
  refineText,
  onPropose,
  onSelect,
  onApprove,
  onDismiss,
  onExecute,
  onRefine,
  onRefineText,
}: {
  update: StrategicUpdate;
  actions: StrategicAction[];
  selectedActionId: string | null;
  refineText: string;
  onPropose: (type: string) => void;
  onSelect: (action: StrategicAction) => void;
  onApprove: (action: StrategicAction) => void;
  onDismiss: (action: StrategicAction) => void;
  onExecute: (action: StrategicAction) => void;
  onRefine: (action: StrategicAction) => void;
  onRefineText: (value: string) => void;
}) {
  const available = actionTypesForUpdate(update.update_type);
  const selected = actions.find((action) => action.id === selectedActionId) || null;
  return (
    <section className="border-t border-outline-variant/10 pt-5">
      <h3 className="mb-3 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/50">Suggested actions</h3>
      <div className="flex flex-wrap gap-2">
        {available.map((type) => <button key={type} type="button" onClick={() => onPropose(type)} className="rounded-lg border border-primary/30 px-3 py-2 text-xs font-bold text-primary hover:bg-primary/10">{label(type)}</button>)}
        {actions.map((action) => <button key={action.id} type="button" onClick={() => onSelect(action)} className="rounded-lg border border-outline-variant/20 px-3 py-2 text-xs font-semibold text-on-surface-variant hover:border-primary/30 hover:text-primary">{label(action.action_type)} · {label(action.status)}</button>)}
      </div>
      {selected && (
        <div className="mt-4 rounded-xl border border-primary/20 bg-surface-container-low p-4">
          <div className="mb-4 flex items-center justify-between gap-3"><div><p className="text-[10px] font-bold uppercase tracking-widest text-primary">Proposed change</p><p className="mt-1 text-xs text-on-surface-variant/60">{label(selected.status)} · approval and execution are separate steps</p></div>{selected.status === "completed" && <span className="text-xs font-bold text-secondary">Completed</span>}</div>
          <div className="grid gap-4 text-sm md:grid-cols-2"><div><p className="mb-1 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/50">What changes</p><p className="text-on-surface">{String(selected.proposal.what_changes || "Review the proposed operational change below.")}</p></div><div><p className="mb-1 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/50">Why</p><p className="text-on-surface">{String(selected.proposal.recommendation || update.recommendation)}</p></div></div>
          <div className="mt-4"><p className="mb-1 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/50">Proposed payload</p><pre className="max-h-48 overflow-auto rounded-lg bg-surface-lowest p-3 text-[11px] leading-relaxed text-on-surface-variant">{JSON.stringify(selected.proposal.proposed_change || {}, null, 2)}</pre></div>
          {selected.error && <p className="mt-3 text-xs text-error">{selected.error}</p>}
          {String(selected.result.entity_id || "") && <p className="mt-3 text-xs text-secondary">Result: {label(String(selected.result.entity_type || "record"))} {String(selected.result.entity_id)}</p>}
          {(selected.status === "proposed" || selected.status === "failed") && <div className="mt-4"><label className="block text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/50">Refine proposed change (JSON)</label><textarea value={refineText} onChange={(event) => onRefineText(event.target.value)} className="mt-1.5 min-h-20 w-full rounded-lg border border-outline-variant/20 bg-surface-lowest p-3 text-xs text-on-surface outline-none focus:border-primary/50" /></div>}
          <div className="mt-4 flex flex-wrap justify-end gap-2">{(selected.status === "proposed" || selected.status === "failed") && <><button type="button" onClick={() => onRefine(selected)} className="rounded-lg border border-outline-variant/20 px-3 py-2 text-xs font-semibold text-on-surface-variant">Refine</button><button type="button" onClick={() => onDismiss(selected)} className="rounded-lg border border-error/30 px-3 py-2 text-xs font-semibold text-error">Dismiss</button><button type="button" onClick={() => onApprove(selected)} className="rounded-lg bg-primary px-3 py-2 text-xs font-bold text-on-primary">Approve</button></>}{selected.status === "approved" && <button type="button" onClick={() => onExecute(selected)} className="rounded-lg bg-primary px-3 py-2 text-xs font-bold text-on-primary">Execute approved action</button>}</div>
        </div>
      )}
    </section>
  );
}

function UpdateCard({
  update,
  expanded,
  onToggle,
  onArchive,
  actions,
  selectedActionId,
  refineText,
  onPropose,
  onSelectAction,
  onApproveAction,
  onDismissAction,
  onExecuteAction,
  onRefineAction,
  onRefineText,
}: {
  update: StrategicUpdate;
  expanded: boolean;
  onToggle: () => void;
  onArchive: () => void;
  actions: StrategicAction[];
  selectedActionId: string | null;
  refineText: string;
  onPropose: (type: string) => void;
  onSelectAction: (action: StrategicAction) => void;
  onApproveAction: (action: StrategicAction) => void;
  onDismissAction: (action: StrategicAction) => void;
  onExecuteAction: (action: StrategicAction) => void;
  onRefineAction: (action: StrategicAction) => void;
  onRefineText: (value: string) => void;
}) {
  return (
    <article className={`rounded-xl border bg-surface-lowest transition-colors ${expanded ? "border-primary/25" : "border-outline-variant/15 hover:border-outline-variant/30"}`}>
      <button type="button" onClick={onToggle} className="w-full px-5 py-5 text-left">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-primary/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-primary">{label(update.update_type)}</span>
              <span className="rounded-full bg-surface-container-high px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant/70">{label(update.confidence)} confidence</span>
            </div>
            <h2 className="font-serif text-2xl font-normal text-on-surface">{update.title}</h2>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-on-surface-variant/75">{update.summary}</p>
          </div>
          <Icon name="chevron_right" className={`mt-1 shrink-0 text-lg text-on-surface-variant/50 transition-transform ${expanded ? "rotate-90" : ""}`} />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-on-surface-variant/50">
          <span>{update.evidence.length} evidence reference{update.evidence.length === 1 ? "" : "s"}</span>
          <span>Observed {dateLabel(update.observed_at)}</span>
          <span>Updated {dateLabel(update.updated_at)}</span>
        </div>
      </button>

      {expanded && (
        <div className="space-y-5 border-t border-outline-variant/10 px-5 pb-5 pt-5">
          <div className="grid gap-5 md:grid-cols-3">
            <section><h3 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/50">Observation</h3><p className="text-sm leading-relaxed text-on-surface">{update.observation}</p></section>
            <section><h3 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/50">Interpretation</h3><p className="text-sm leading-relaxed text-on-surface">{update.interpretation}</p></section>
            <section><h3 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/50">Recommendation</h3><p className="text-sm leading-relaxed text-on-surface">{update.recommendation}</p></section>
          </div>
          <section>
            <div className="mb-3 flex items-center justify-between gap-3"><h3 className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/50">Evidence</h3><button type="button" onClick={onArchive} className="text-xs font-semibold text-error hover:underline">Archive update</button></div>
            <EvidenceList evidence={update.evidence} />
          </section>
          <ActionSection update={update} actions={actions} selectedActionId={selectedActionId} refineText={refineText} onPropose={onPropose} onSelect={onSelectAction} onApprove={onApproveAction} onDismiss={onDismissAction} onExecute={onExecuteAction} onRefine={onRefineAction} onRefineText={onRefineText} />
        </div>
      )}
    </article>
  );
}

export default function StrategicUpdatePage() {
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [updates, setUpdates] = useState<StrategicUpdate[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updateType, setUpdateType] = useState("all");
  const [confidence, setConfidence] = useState("all");
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [lastAnalyzed, setLastAnalyzed] = useState<string | null>(null);
  const [actionsByUpdate, setActionsByUpdate] = useState<Record<string, StrategicAction[]>>({});
  const [selectedActionId, setSelectedActionId] = useState<string | null>(null);
  const [refineText, setRefineText] = useState("{}");

  usePageContext("Strategic Updates", { updates: updates.length, lastAnalyzed });

  useEffect(() => {
    try { setSessionToken(localStorage.getItem(ACTIVE_SESSION_KEY)); } catch { setSessionToken(null); }
  }, []);

  const load = useCallback(async (token: string) => {
    setLoading(true);
    setError(null);
    try {
      const response = await listStrategicUpdates(token);
      setUpdates(response.updates || []);
      setLastAnalyzed(response.last_analyzed || null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Strategic Updates could not be loaded");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (sessionToken) void load(sessionToken);
    else setLoading(false);
  }, [sessionToken, load]);

  async function loadActions(updateId: string) {
    if (!sessionToken) return;
    try {
      const response = await listStrategicActions(sessionToken, updateId);
      setActionsByUpdate((current) => ({ ...current, [updateId]: response.actions || [] }));
    } catch (cause) {
      toast("error", cause instanceof Error ? cause.message : "Actions could not be loaded");
    }
  }

  async function toggleUpdate(update: StrategicUpdate) {
    const opening = expandedId !== update.id;
    setExpandedId(opening ? update.id : null);
    setSelectedActionId(null);
    if (opening) await loadActions(update.id);
  }

  function patchAction(action: StrategicAction) {
    setActionsByUpdate((current) => ({
      ...current,
      [action.strategic_update_id]: (current[action.strategic_update_id] || []).map((item) => item.id === action.id ? action : item),
    }));
    setSelectedActionId(action.id);
  }

  async function propose(update: StrategicUpdate, actionType: string) {
    if (!sessionToken) return;
    try {
      const response = await proposeStrategicAction(sessionToken, update.id, actionType);
      setActionsByUpdate((current) => ({ ...current, [update.id]: [...(current[update.id] || []).filter((item) => item.id !== response.action.id), response.action] }));
      setSelectedActionId(response.action.id);
      setRefineText(JSON.stringify(response.action.proposal.proposed_change || {}, null, 2));
    } catch (cause) {
      toast("error", cause instanceof Error ? cause.message : "Action could not be proposed");
    }
  }

  async function approve(action: StrategicAction) {
    if (!sessionToken) return;
    try { patchAction((await approveStrategicAction(sessionToken, action.id)).action); toast("success", "Action approved. Review it once more, then execute it."); }
    catch (cause) { toast("error", cause instanceof Error ? cause.message : "Action could not be approved"); }
  }

  async function dismiss(action: StrategicAction) {
    if (!sessionToken) return;
    try { patchAction((await dismissStrategicAction(sessionToken, action.id)).action); toast("info", "Action dismissed"); }
    catch (cause) { toast("error", cause instanceof Error ? cause.message : "Action could not be dismissed"); }
  }

  async function refine(action: StrategicAction) {
    if (!sessionToken) return;
    try {
      const changes = JSON.parse(refineText) as Record<string, unknown>;
      patchAction((await refineStrategicAction(sessionToken, action.id, changes)).action);
      toast("success", "Proposal refined");
    } catch (cause) {
      toast("error", cause instanceof Error ? cause.message : "Refinement must be valid JSON");
    }
  }

  async function execute(action: StrategicAction) {
    if (!sessionToken) return;
    try { patchAction((await executeStrategicAction(sessionToken, action.id)).action); toast("success", "Action execution finished"); }
    catch (cause) { toast("error", cause instanceof Error ? cause.message : "Action could not be executed"); }
  }

  const visibleUpdates = useMemo(() => {
    const query = search.trim().toLowerCase();
    return updates.filter((update) =>
      (updateType === "all" || update.update_type === updateType) &&
      (confidence === "all" || update.confidence === confidence) &&
      (!query || JSON.stringify(update).toLowerCase().includes(query)),
    );
  }, [confidence, search, updateType, updates]);

  async function refresh() {
    if (!sessionToken || refreshing) return;
    setRefreshing(true);
    setError(null);
    try {
      const response = await refreshStrategicUpdates(sessionToken);
      setUpdates(response.updates || []);
      setLastAnalyzed(response.last_analyzed || null);
      toast("success", response.new_updates ? `${response.new_updates} strategic update${response.new_updates === 1 ? "" : "s"} found` : "Intelligence refreshed");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Intelligence could not be refreshed");
    } finally {
      setRefreshing(false);
    }
  }

  async function archive(update: StrategicUpdate) {
    if (!sessionToken || !window.confirm("Archive this Strategic Update?")) return;
    try {
      await archiveStrategicUpdate(sessionToken, update.id);
      setUpdates((current) => current.filter((item) => item.id !== update.id));
      setExpandedId(null);
      toast("success", "Strategic Update archived");
    } catch (cause) {
      toast("error", cause instanceof Error ? cause.message : "Update could not be archived");
    }
  }

  if (loading) {
    return <WorkspaceContainer><AppPage><div className="mx-auto w-full max-w-5xl space-y-6 py-8 animate-skeleton-pulse"><div className="h-10 w-64 rounded-lg bg-surface-high/50" /><div className="h-4 w-96 max-w-full rounded bg-surface-high/50" />{[1, 2, 3].map((key) => <div key={key} className="h-40 rounded-xl bg-surface-lowest" />)}</div></AppPage></WorkspaceContainer>;
  }

  if (error && updates.length === 0) {
    return <WorkspaceContainer><AppPage><div className="mx-auto w-full max-w-5xl py-16"><EmptyState icon="cloud_off" title="Strategic Updates are unavailable" description={error} action={sessionToken ? { label: "Retry", onClick: () => void load(sessionToken) } : undefined} /></div></AppPage></WorkspaceContainer>;
  }

  const types = [...new Set(updates.map((update) => update.update_type))].sort();

  return (
    <WorkspaceContainer>
      <AppPage className="overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl space-y-8 py-4 pb-16">
          <header className="flex flex-col gap-5 border-b border-outline-variant/10 pb-7 md:flex-row md:items-end md:justify-between">
            <div><p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">Evidence-backed briefing</p><p className="max-w-xl font-serif text-xl leading-snug text-on-surface">Patterns Loqi found across your outbound activity. Recommendations are suggestions only; operational state is never changed automatically.</p>{lastAnalyzed && <p className="mt-3 text-[11px] text-on-surface-variant/50">Last analyzed {dateLabel(lastAnalyzed)}</p>}</div>
            <button type="button" onClick={() => void refresh()} disabled={!sessionToken || refreshing} className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-xs font-bold text-on-primary transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"><Icon name="refresh" className={refreshing ? "animate-spin" : ""} />{refreshing ? "Refreshing..." : "Refresh intelligence"}</button>
          </header>

          <div className="flex flex-col gap-3 sm:flex-row"><label className="flex flex-1 items-center gap-2 rounded-lg border border-outline-variant/20 bg-surface-lowest px-3 py-2"><Icon name="search" className="text-base text-on-surface-variant/50" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search updates" className="min-w-0 flex-1 bg-transparent text-sm text-on-surface outline-none placeholder:text-on-surface-variant/40" /></label><select value={updateType} onChange={(event) => setUpdateType(event.target.value)} className="rounded-lg border border-outline-variant/20 bg-surface-lowest px-3 py-2 text-sm text-on-surface outline-none"><option value="all">All types</option>{types.map((type) => <option key={type} value={type}>{label(type)}</option>)}</select><select value={confidence} onChange={(event) => setConfidence(event.target.value)} className="rounded-lg border border-outline-variant/20 bg-surface-lowest px-3 py-2 text-sm text-on-surface outline-none"><option value="all">All confidence</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></div>

          {visibleUpdates.length === 0 ? <EmptyState icon="insights" title={updates.length ? "No updates match these filters" : "Not enough activity yet"} description={updates.length ? "Try a different update type, confidence level, or search term." : "Strategic Intelligence needs real campaigns, messages, and conversations before it can surface an evidence-backed pattern."} action={updates.length ? undefined : { label: "Refresh intelligence", onClick: () => void refresh() }} /> : <div className="space-y-4">{visibleUpdates.map((update) => <UpdateCard key={update.id} update={update} expanded={expandedId === update.id} onToggle={() => void toggleUpdate(update)} onArchive={() => void archive(update)} actions={actionsByUpdate[update.id] || []} selectedActionId={selectedActionId} refineText={refineText} onPropose={(type) => void propose(update, type)} onSelectAction={(action) => { setSelectedActionId(action.id); setRefineText(JSON.stringify(action.proposal.proposed_change || {}, null, 2)); }} onApproveAction={(action) => void approve(action)} onDismissAction={(action) => void dismiss(action)} onExecuteAction={(action) => void execute(action)} onRefineAction={(action) => void refine(action)} onRefineText={setRefineText} />)}</div>}
        </div>
      </AppPage>
    </WorkspaceContainer>
  );
}
