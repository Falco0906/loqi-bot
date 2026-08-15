"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import WorkspaceContainer from "../../../components/layout/WorkspaceContainer";
import AppPage from "../../../components/primitives/AppPage";
import EmptyState from "../../../components/shared/EmptyState";
import Icon from "../../../components/shared/Icon";
import { toast } from "../../../components/shared/Toast";
import { usePageContext } from "../../../hooks/usePageContext";
import {
  archiveKnowledgeItem,
  archiveKnowledgeSource,
  createKnowledgeItem,
  createKnowledgeSource,
  listKnowledge,
  listKnowledgeSources,
  updateKnowledgeItem,
  updateKnowledgeSource,
  type KnowledgeCategory,
  type KnowledgeItem,
  type KnowledgeItemPayload,
  type KnowledgeItemSourceType,
  type KnowledgeSource,
  type KnowledgeSourcePayload,
  type KnowledgeSourceType,
} from "../../../lib/api";

const ACTIVE_SESSION_KEY = "loqi_active_session_token";

const CATEGORY_CONFIG: Array<{
  key: KnowledgeCategory;
  label: string;
  description: string;
  icon: string;
}> = [
  { key: "company", label: "Company", description: "Products, positioning, differentiators and business context.", icon: "add_business" },
  { key: "icp", label: "Ideal Customer Profile", description: "Who Loqi should target and who it should avoid.", icon: "groups" },
  { key: "messaging", label: "Messaging", description: "Approved positioning, voice, claims and angles.", icon: "forum" },
  { key: "sales_offer", label: "Sales & Proof", description: "Offers, use cases, objections, FAQs and proof points.", icon: "monetization_on" },
];

const ITEM_SOURCE_TYPES: Array<{ value: KnowledgeItemSourceType; label: string }> = [
  { value: "user_input", label: "User input" },
  { value: "uploaded_document", label: "Uploaded document" },
  { value: "imported_source", label: "Imported source" },
  { value: "system_generated", label: "System generated" },
];

const SOURCE_TYPES: Array<{ value: KnowledgeSourceType; label: string }> = [
  { value: "user_input", label: "Note / user input" },
  { value: "uploaded_document", label: "Uploaded document" },
  { value: "imported_source", label: "Imported source" },
  { value: "system_generated", label: "System generated" },
];

type ItemForm = {
  category: KnowledgeCategory;
  title: string;
  summary: string;
  content: string;
  tags: string;
  source_type: KnowledgeItemSourceType;
  source_id: string;
};

type SourceForm = {
  title: string;
  source_type: KnowledgeSourceType;
  content: string;
  reference: string;
};

const emptyItemForm = (category: KnowledgeCategory = "company"): ItemForm => ({
  category,
  title: "",
  summary: "",
  content: "",
  tags: "",
  source_type: "user_input",
  source_id: "",
});

const emptySourceForm = (): SourceForm => ({
  title: "",
  source_type: "user_input",
  content: "",
  reference: "",
});

function updatedLabel(value: string | null): string {
  if (!value) return "Not dated";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not dated";
  return `Updated ${date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;
}

function sourceLabel(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-obsidian/55 px-4 backdrop-blur-sm" role="dialog" aria-modal="true">
      <button type="button" aria-label="Close dialog" className="absolute inset-0 cursor-default" onClick={onClose} />
      <div className="relative z-10 max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-outline-variant/20 bg-surface-container-low p-6 shadow-2xl">
        <div className="mb-6 flex items-center justify-between gap-4">
          <h2 className="font-serif text-2xl text-on-surface">{title}</h2>
          <button type="button" onClick={onClose} className="rounded-lg p-2 text-on-surface-variant/60 hover:bg-surface-container-high hover:text-on-surface" aria-label="Close">
            <Icon name="close" className="text-lg" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
  multiline = false,
  placeholder,
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  multiline?: boolean;
  placeholder?: string;
  required?: boolean;
}) {
  const className = "mt-1.5 w-full rounded-lg border border-outline-variant/20 bg-surface-lowest px-3 py-2.5 text-sm text-on-surface outline-none transition focus:border-primary/60";
  return (
    <label className="block text-xs font-semibold text-on-surface-variant">
      {label}{required ? " *" : ""}
      {multiline ? (
        <textarea className={`${className} min-h-24 resize-y`} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
      ) : (
        <input className={className} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
      )}
    </label>
  );
}

function TypeSelect<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (value: T) => void;
}) {
  return (
    <label className="block text-xs font-semibold text-on-surface-variant">
      {label}
      <select className="mt-1.5 w-full rounded-lg border border-outline-variant/20 bg-surface-lowest px-3 py-2.5 text-sm text-on-surface outline-none focus:border-primary/60" value={value} onChange={(event) => onChange(event.target.value as T)}>
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  );
}

export default function KnowledgePage() {
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [itemModal, setItemModal] = useState<KnowledgeItem | null | false>(false);
  const [itemForm, setItemForm] = useState<ItemForm>(emptyItemForm());
  const [sourceModal, setSourceModal] = useState<KnowledgeSource | null | false>(false);
  const [sourceForm, setSourceForm] = useState<SourceForm>(emptySourceForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  usePageContext("Knowledge", { items: items.length, sources: sources.length });

  useEffect(() => {
    try {
      setSessionToken(localStorage.getItem(ACTIVE_SESSION_KEY));
    } catch {
      setSessionToken(null);
    }
  }, []);

  const load = useCallback(async (token: string) => {
    setLoading(true);
    setError(null);
    try {
      const [itemResponse, sourceResponse] = await Promise.all([
        listKnowledge(token),
        listKnowledgeSources(token),
      ]);
      setItems(itemResponse.items || []);
      setSources(sourceResponse.sources || []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Knowledge could not be loaded");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (sessionToken) void load(sessionToken);
    else setLoading(false);
  }, [sessionToken, load]);

  const visibleItems = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return items;
    return items.filter((item) => JSON.stringify(item).toLowerCase().includes(query));
  }, [items, search]);

  function openNewItem(category: KnowledgeCategory) {
    setFormError(null);
    setItemForm(emptyItemForm(category));
    setItemModal(null);
  }

  function openEditItem(item: KnowledgeItem) {
    setFormError(null);
    setItemForm({
      category: item.category,
      title: item.title,
      summary: item.summary,
      content: Object.keys(item.content || {}).length ? JSON.stringify(item.content, null, 2) : "",
      tags: item.tags.join(", "),
      source_type: item.source_type,
      source_id: item.source_id,
    });
    setItemModal(item);
  }

  async function saveItem(event: FormEvent) {
    event.preventDefault();
    if (!sessionToken) return;
    setFormError(null);
    let content: Record<string, unknown> = {};
    if (itemForm.content.trim()) {
      try {
        const parsed: unknown = JSON.parse(itemForm.content);
        if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("JSON must be an object");
        content = parsed as Record<string, unknown>;
      } catch (cause) {
        setFormError(cause instanceof Error ? cause.message : "Content must be valid JSON");
        return;
      }
    }
    const payload: KnowledgeItemPayload = {
      category: itemForm.category,
      title: itemForm.title,
      summary: itemForm.summary,
      content,
      tags: itemForm.tags.split(",").map((tag) => tag.trim()).filter(Boolean),
      source_type: itemForm.source_type,
      source_id: itemForm.source_id,
    };
    setSaving(true);
    try {
      if (itemModal) {
        const response = await updateKnowledgeItem(sessionToken, itemModal.id, payload);
        setItems((current) => current.map((item) => item.id === itemModal.id ? response.item : item));
        toast("success", "Knowledge updated");
      } else {
        const response = await createKnowledgeItem(sessionToken, payload);
        setItems((current) => [response.item, ...current]);
        toast("success", "Knowledge added");
      }
      setItemModal(false);
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : "Knowledge could not be saved");
    } finally {
      setSaving(false);
    }
  }

  async function removeItem() {
    if (!sessionToken || !itemModal || !window.confirm("Archive this Knowledge entry?")) return;
    setSaving(true);
    try {
      await archiveKnowledgeItem(sessionToken, itemModal.id);
      setItems((current) => current.filter((item) => item.id !== itemModal.id));
      setItemModal(false);
      toast("success", "Knowledge archived");
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : "Knowledge could not be archived");
    } finally {
      setSaving(false);
    }
  }

  function openNewSource() {
    setFormError(null);
    setSourceForm(emptySourceForm());
    setSourceModal(null);
  }

  function openEditSource(source: KnowledgeSource) {
    setFormError(null);
    setSourceForm({ title: source.title, source_type: source.source_type, content: source.content, reference: source.reference });
    setSourceModal(source);
  }

  async function saveSource(event: FormEvent) {
    event.preventDefault();
    if (!sessionToken) return;
    setFormError(null);
    const payload: KnowledgeSourcePayload = sourceForm;
    setSaving(true);
    try {
      if (sourceModal) {
        const response = await updateKnowledgeSource(sessionToken, sourceModal.id, payload);
        setSources((current) => current.map((source) => source.id === sourceModal.id ? response.source : source));
        toast("success", "Source updated");
      } else {
        const response = await createKnowledgeSource(sessionToken, payload);
        setSources((current) => [response.source, ...current]);
        toast("success", "Source added");
      }
      setSourceModal(false);
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : "Source could not be saved");
    } finally {
      setSaving(false);
    }
  }

  async function removeSource() {
    if (!sessionToken || !sourceModal || !window.confirm("Archive this source?")) return;
    setSaving(true);
    try {
      await archiveKnowledgeSource(sessionToken, sourceModal.id);
      setSources((current) => current.filter((source) => source.id !== sourceModal.id));
      setSourceModal(false);
      toast("success", "Source archived");
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : "Source could not be archived");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <WorkspaceContainer><AppPage><div className="mx-auto w-full max-w-5xl space-y-6 py-8 animate-skeleton-pulse">
        <div className="h-10 w-48 rounded-lg bg-surface-high/50" />
        <div className="h-4 w-96 max-w-full rounded bg-surface-high/50" />
        {[1, 2, 3].map((key) => <div key={key} className="h-28 rounded-xl bg-surface-lowest" />)}
      </div></AppPage></WorkspaceContainer>
    );
  }

  if (error) {
    return (
      <WorkspaceContainer><AppPage><div className="mx-auto w-full max-w-5xl py-16">
        <EmptyState icon="cloud_off" title="Knowledge is unavailable" description={error} action={sessionToken ? { label: "Retry", onClick: () => void load(sessionToken) } : undefined} />
      </div></AppPage></WorkspaceContainer>
    );
  }

  return (
    <WorkspaceContainer>
      <AppPage className="overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl space-y-8 py-4 pb-16">
          <header className="flex flex-col gap-5 border-b border-outline-variant/10 pb-7 md:flex-row md:items-end md:justify-between">
            <div>
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">Knowledge foundation</p>
              <h1 className="font-serif text-4xl font-normal text-on-surface">Knowledge</h1>
              <p className="mt-2 max-w-xl text-sm leading-relaxed text-on-surface-variant/75">Everything Loqi knows about your business, kept in one place for the work ahead.</p>
            </div>
            <label className="flex w-full items-center gap-2 rounded-lg border border-outline-variant/20 bg-surface-lowest px-3 py-2 md:max-w-xs">
              <Icon name="search" className="text-base text-on-surface-variant/50" />
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search Knowledge" className="min-w-0 flex-1 bg-transparent text-sm text-on-surface outline-none placeholder:text-on-surface-variant/40" />
            </label>
          </header>

          <div className="space-y-5">
            {CATEGORY_CONFIG.map((section) => {
              const sectionItems = visibleItems.filter((item) => item.category === section.key);
              return (
                <section key={section.key} className="rounded-xl border border-outline-variant/15 bg-surface-lowest/70">
                  <div className="flex items-start justify-between gap-4 border-b border-outline-variant/10 px-5 py-4">
                    <div className="flex min-w-0 gap-3">
                      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Icon name={section.icon} className="text-base" /></div>
                      <div><h2 className="text-sm font-bold text-on-surface">{section.label}</h2><p className="mt-1 text-xs text-on-surface-variant/60">{section.description}</p></div>
                    </div>
                    <button type="button" onClick={() => openNewItem(section.key)} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-primary/30 px-3 py-2 text-xs font-bold text-primary hover:bg-primary/10"><Icon name="add_circle" className="text-sm" /> Add</button>
                  </div>
                  {sectionItems.length === 0 ? (
                    <div className="px-5 py-7 text-sm text-on-surface-variant/50">No {section.label.toLowerCase()} added yet. Add the context Loqi should use as a source of truth.</div>
                  ) : (
                    <div className="divide-y divide-outline-variant/10">
                      {sectionItems.map((item) => (
                        <button type="button" key={item.id} onClick={() => openEditItem(item)} className="group flex w-full items-start justify-between gap-4 px-5 py-4 text-left hover:bg-surface-container-low">
                          <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="truncate text-sm font-semibold text-on-surface">{item.title}</span><span className="rounded-full bg-surface-container-high px-2 py-0.5 text-[10px] text-on-surface-variant/70">{sourceLabel(item.source_type)}</span></div><p className="mt-1 line-clamp-2 text-xs leading-relaxed text-on-surface-variant/65">{item.summary || "Structured Knowledge entry"}</p>{item.tags.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{item.tags.map((tag) => <span key={tag} className="rounded-full border border-outline-variant/15 px-2 py-0.5 text-[10px] text-on-surface-variant/55">{tag}</span>)}</div>}</div>
                          <span className="flex shrink-0 items-center gap-2 text-[10px] text-on-surface-variant/40"><span className="hidden sm:inline">{updatedLabel(item.updated_at)}</span><Icon name="chevron_right" className="text-sm transition-transform group-hover:translate-x-0.5" /></span>
                        </button>
                      ))}
                    </div>
                  )}
                </section>
              );
            })}

            <section className="rounded-xl border border-outline-variant/15 bg-surface-lowest/70">
              <div className="flex items-start justify-between gap-4 border-b border-outline-variant/10 px-5 py-4">
                <div className="flex min-w-0 gap-3"><div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-secondary/10 text-secondary"><Icon name="folder_zip" className="text-base" /></div><div><h2 className="text-sm font-bold text-on-surface">Sources</h2><p className="mt-1 text-xs text-on-surface-variant/60">Notes, documents and imported material with preserved provenance.</p></div></div>
                <button type="button" onClick={openNewSource} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-secondary/30 px-3 py-2 text-xs font-bold text-secondary hover:bg-secondary/10"><Icon name="add_circle" className="text-sm" /> Add source</button>
              </div>
              {sources.length === 0 ? <div className="px-5 py-7 text-sm text-on-surface-variant/50">No sources added yet. Add a note or a reference to source material when it is ready.</div> : <div className="divide-y divide-outline-variant/10">{sources.filter((source) => !search.trim() || JSON.stringify(source).toLowerCase().includes(search.trim().toLowerCase())).map((source) => <button type="button" key={source.id} onClick={() => openEditSource(source)} className="group flex w-full items-start justify-between gap-4 px-5 py-4 text-left hover:bg-surface-container-low"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="truncate text-sm font-semibold text-on-surface">{source.title}</span><span className="rounded-full bg-surface-container-high px-2 py-0.5 text-[10px] text-on-surface-variant/70">{sourceLabel(source.source_type)}</span></div><p className="mt-1 line-clamp-2 text-xs leading-relaxed text-on-surface-variant/65">{source.content || source.reference || "Referenced source material"}</p></div><span className="flex shrink-0 items-center gap-2 text-[10px] text-on-surface-variant/40"><span className="hidden sm:inline">{updatedLabel(source.updated_at)}</span><Icon name="chevron_right" className="text-sm transition-transform group-hover:translate-x-0.5" /></span></button>)}</div>}
            </section>
          </div>
        </div>
      </AppPage>

      {itemModal !== false && <Modal title={itemModal ? "Edit Knowledge" : "Add Knowledge"} onClose={() => setItemModal(false)}><form onSubmit={saveItem} className="space-y-4"><TypeSelect label="Category" value={itemForm.category} options={CATEGORY_CONFIG.map(({ key, label }) => ({ value: key, label }))} onChange={(value) => setItemForm((form) => ({ ...form, category: value }))} /><TextField label="Title" value={itemForm.title} onChange={(value) => setItemForm((form) => ({ ...form, title: value }))} placeholder="e.g. Core positioning" required /><TextField label="Summary" value={itemForm.summary} onChange={(value) => setItemForm((form) => ({ ...form, summary: value }))} placeholder="A concise explanation future agents can use" multiline /><TextField label="Structured content (JSON)" value={itemForm.content} onChange={(value) => setItemForm((form) => ({ ...form, content: value }))} placeholder={'{"products": ["..."]}'} multiline /><TextField label="Tags" value={itemForm.tags} onChange={(value) => setItemForm((form) => ({ ...form, tags: value }))} placeholder="product, positioning" /><TypeSelect label="Provenance" value={itemForm.source_type} options={ITEM_SOURCE_TYPES} onChange={(value) => setItemForm((form) => ({ ...form, source_type: value }))} /><TextField label="Source ID / reference" value={itemForm.source_id} onChange={(value) => setItemForm((form) => ({ ...form, source_id: value }))} placeholder="Optional source ID" />{formError && <p className="text-xs text-error">{formError}</p>}<div className="flex items-center justify-between gap-3 pt-2">{itemModal ? <button type="button" onClick={() => void removeItem()} className="text-xs font-semibold text-error hover:underline">Archive</button> : <span /> }<div className="flex gap-2"><button type="button" onClick={() => setItemModal(false)} className="rounded-lg border border-outline-variant/20 px-4 py-2 text-xs font-semibold text-on-surface-variant">Cancel</button><button type="submit" disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-xs font-bold text-on-primary disabled:opacity-50">{saving ? "Saving..." : itemModal ? "Save changes" : "Add Knowledge"}</button></div></div></form></Modal>}

      {sourceModal !== false && <Modal title={sourceModal ? "Edit Source" : "Add Source"} onClose={() => setSourceModal(false)}><form onSubmit={saveSource} className="space-y-4"><TextField label="Title" value={sourceForm.title} onChange={(value) => setSourceForm((form) => ({ ...form, title: value }))} placeholder="e.g. Pricing notes" required /><TypeSelect label="Source type" value={sourceForm.source_type} options={SOURCE_TYPES} onChange={(value) => setSourceForm((form) => ({ ...form, source_type: value }))} /><TextField label="Content" value={sourceForm.content} onChange={(value) => setSourceForm((form) => ({ ...form, content: value }))} placeholder="Enter a note, or leave blank when using a reference" multiline /><TextField label="Reference" value={sourceForm.reference} onChange={(value) => setSourceForm((form) => ({ ...form, reference: value }))} placeholder="Optional file or external reference" />{formError && <p className="text-xs text-error">{formError}</p>}<div className="flex items-center justify-between gap-3 pt-2">{sourceModal ? <button type="button" onClick={() => void removeSource()} className="text-xs font-semibold text-error hover:underline">Archive</button> : <span /> }<div className="flex gap-2"><button type="button" onClick={() => setSourceModal(false)} className="rounded-lg border border-outline-variant/20 px-4 py-2 text-xs font-semibold text-on-surface-variant">Cancel</button><button type="submit" disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-xs font-bold text-on-primary disabled:opacity-50">{saving ? "Saving..." : sourceModal ? "Save changes" : "Add source"}</button></div></div></form></Modal>}
    </WorkspaceContainer>
  );
}
