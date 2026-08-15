"""Discovery service — first-class, persistent research entities.

A Discovery is the durable, per-run record of ONE research run (schema 014).
It owns the query, lifecycle status, and the ``jobs`` rows that produced it:
the relationship is Discovery → many Jobs, persisted as ``jobs.discovery_id``
(a nullable FK, ON DELETE SET NULL), so a discovery can later be refreshed,
rerun, or scheduled without changing ownership. Surfaced companies and leads
are LINKS into the canonical schema (007 companies / leads /
workspace_companies / workspace_leads) — the discovery never duplicates data;
it only adds per-run rank / match score / provenance (discovery_companies /
discovery_leads).

Design notes
------------
* A search job stays transient (``search_results`` is staging). The Discovery
  is the ownership root and survives long after the job is purged.
* The discovery row is created FIRST, then the search job is enqueued with
  ``discovery_id`` baked in — there is no window where the two can drift apart.
* ``finalize_discovery`` runs from the job runner's ``on_complete`` hook, in
  the event loop, so it can await the canonical ``_normalize_lead`` path and
  reuses the exact global-dedup logic every other surface uses.
* Idempotent: a discovery is finalized at most once.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from services.supabase import get_supabase_client

_DISCOVERY_SELECT = (
    "id, workspace_id, query, status, title, description, favorite, "
    "archived_at, last_viewed_at, last_refreshed_at, metadata, summary, "
    "filters, provider_provenance, created_by, updated_by, version, "
    "created_at, updated_at, completed_at, deleted_at"
)


def _log(msg: str) -> None:
    print(f"[discovery] {msg}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _count_of(payload: Any) -> int:
    try:
        return int(payload[0]["count"])
    except Exception:
        return 0


def create_discovery(
    workspace_id: str,
    user_id: str,
    query: str,
) -> Optional[dict]:
    """Persist a new discovery row (no job link yet).

    Called synchronously (via ``asyncio.to_thread``) BEFORE the search job is
    enqueued. The caller then creates the job with ``discovery_id`` so the
    relationship lives on the job side (``jobs.discovery_id``). Status starts
    at ``searching``; ``finalize_discovery`` moves it to ``completed``/
    ``failed`` using the job's outcome.

    Creation defaults (everything else stays empty/false):
    ``title = query``, ``last_viewed_at = created_at``, and
    ``last_refreshed_at = created_at``.
    """
    client = get_supabase_client()
    if not client or not workspace_id:
        return None
    now = _now()
    row = {
        "workspace_id": workspace_id,
        "query": str(query or ""),
        "status": "searching",
        "title": str(query or ""),
        "last_viewed_at": now,
        "last_refreshed_at": now,
        "summary": {},
        "metadata": {},
        "filters": [],
        "provider_provenance": {},
        "created_by": user_id,
        "updated_by": user_id,
        "version": 1,
    }
    try:
        result = client.table("discoveries").insert(row).execute()
        created = result.data[0] if getattr(result, "data", None) else row
        _log(f"created discovery {created.get('id')} (waiting for job link)")
        return created
    except Exception as e:
        _log(f"create_discovery error: {e}")
        return None


def get_discovery_id_for_job(job_id: str) -> str:
    """Resolve a discovery through ``jobs.discovery_id`` (Job → Discovery)."""
    client = get_supabase_client()
    if not client or not job_id:
        return ""
    try:
        result = (
            client.table("jobs")
            .select("discovery_id")
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        return str(rows[0].get("discovery_id") or "") if rows else ""
    except Exception as e:
        _log(f"get_discovery_id_for_job error: {e}")
        return ""


def get_discovery_by_job_id(job_id: str) -> Optional[dict]:
    """Fetch the discovery behind a job, resolved through the job's FK."""
    discovery_id = get_discovery_id_for_job(job_id)
    if not discovery_id:
        return None
    client = get_supabase_client()
    try:
        result = (
            client.table("discoveries")
            .select(_DISCOVERY_SELECT)
            .eq("id", discovery_id)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        return rows[0] if rows else None
    except Exception as e:
        _log(f"get_discovery_by_job_id error: {e}")
        return None


def list_discoveries(workspace_id: str, limit: int = 100) -> list[dict]:
    """Recent discoveries for a workspace with their company/lead counts."""
    client = get_supabase_client()
    if not client:
        return []
    try:
        result = (
            client.table("discoveries")
            .select(
                f"{_DISCOVERY_SELECT}, "
                "company_count:discovery_companies(count), "
                "lead_count:discovery_leads(count)"
            )
            .eq("workspace_id", workspace_id)
            .is_("deleted_at", "null")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        for row in rows:
            row["company_count"] = _count_of(row.pop("company_count", None))
            row["lead_count"] = _count_of(row.pop("lead_count", None))
        return rows
    except Exception as e:
        _log(f"list_discoveries error: {e}")
        return []


def get_discovery(discovery_id: str) -> Optional[dict]:
    """Full discovery detail: row + surfaced companies + leads (joined)."""
    client = get_supabase_client()
    if not client:
        return None
    try:
        result = (
            client.table("discoveries")
            .select(
                f"{_DISCOVERY_SELECT}, "
                "discovery_companies(rank, match_score, "
                "company_id, company:companies(*)), "
                "discovery_leads(rank, match_score, status, "
                "lead_id, workspace_lead:workspace_leads("
                "id, company_id, email, first_name, last_name, title, phone, "
                "linkedin_url, lead_status, source, metadata, "
                "lead:leads(*)))"
            )
            .eq("id", discovery_id)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        return rows[0] if rows else None
    except Exception as e:
        _log(f"get_discovery error: {e}")
        return None


def mark_discovery_status(discovery_id: str, status: str, error: str = "") -> bool:
    """Lightweight status transition (used for failed/cancelled jobs)."""
    client = get_supabase_client()
    if not client or not discovery_id:
        return False
    try:
        updates: dict[str, Any] = {
            "status": status,
            "updated_at": _now(),
        }
        if error:
            summary = {"error": error}
            updates["summary"] = summary
        if status in ("completed", "failed", "cancelled"):
            updates["completed_at"] = _now()
        client.table("discoveries").update(updates).eq("id", discovery_id).execute()
        return True
    except Exception as e:
        _log(f"mark_discovery_status error: {e}")
        return False


async def finalize_discovery(job) -> bool:
    """Move a discovery to ``completed`` using its job's stored results.

    Called from the runner's ``on_complete`` hook (event loop context).
    Idempotent — a discovery is never re-finalized. Every step degrades
    gracefully so a partial failure can never lose an otherwise good run.
    """
    try:
        discovery_id = str(getattr(job, "discovery_id", "") or "")
        _log(f"[kickoff] finalize_discovery entered: job={getattr(job, 'id', '')} discovery_id={discovery_id or '(empty, resolving via job FK)'}")
        row = None
        if discovery_id:
            client = get_supabase_client()
            try:
                result = (
                    client.table("discoveries")
                    .select(_DISCOVERY_SELECT)
                    .eq("id", discovery_id)
                    .limit(1)
                    .execute()
                )
                rows = getattr(result, "data", None) or []
                row = rows[0] if rows else None
            except Exception as e:
                _log(f"finalize_discovery fetch error: {e}")
                row = None
        if not row:
            _log(f"[kickoff] finalize_discovery: falling back to get_discovery_by_job_id({getattr(job, 'id', '')})")
            row = await asyncio.to_thread(get_discovery_by_job_id, job.id)
        if not row:
            _log(f"[kickoff] finalize_discovery: ABORT — no discovery row for job {getattr(job, 'id', '')}, returning False silently")
            return False
        _log(f"[kickoff] finalize_discovery: row found id={row.get('id')} status={row.get('status')}")
        discovery_id = str(row["id"])
        if row.get("status") in ("completed", "cancelled"):
            return True

        workspace_id = str(row.get("workspace_id") or "")
        if not workspace_id:
            await asyncio.to_thread(mark_discovery_status, discovery_id, "failed", "No workspace")
            return False

        from services.job_engine.storage import JobStorage
        leads = await asyncio.to_thread(JobStorage().get_search_results, job.id)
        _log(f"[kickoff] finalize_discovery: search_results={len(leads) if leads else 0} for job {getattr(job, 'id', '')}")

        from services.workspace_state import _normalize_lead

        ws_lead_ids: list[str] = []
        seen: set[str] = set()
        providers: dict[str, int] = {}
        for lead in leads:
            provider = str(lead.get("provider") or lead.get("source") or "search")
            providers[provider] = providers.get(provider, 0) + 1
            try:
                ws_lead_id = await _normalize_lead(workspace_id, lead)
            except Exception as e:
                _log(f"finalize_discovery normalize lead skipped: {e}")
                continue
            if ws_lead_id and ws_lead_id not in seen:
                seen.add(ws_lead_id)
                ws_lead_ids.append(ws_lead_id)
    except Exception as e:
        _log(f"finalize_discovery failed: {e}")
        if row:
            await asyncio.to_thread(mark_discovery_status, str(row["id"]), "failed", str(e))
        return False

    linked = await asyncio.to_thread(_link_leads, discovery_id, leads, ws_lead_ids)
    companies_linked = await asyncio.to_thread(
        _link_companies, discovery_id, workspace_id, ws_lead_ids
    )

    company_count = lead_count = 0
    if companies_linked is not None:
        company_count = companies_linked
    if linked is not None:
        lead_count = linked

    summary = {
        "brief": (
            f"Researched '{row.get('query') or job.query}'. "
            f"Surfaced {company_count} compan{'y' if company_count == 1 else 'ies'} "
            f"and {lead_count} lead{'s' if lead_count != 1 else ''}."
        ),
        "company_count": company_count,
        "lead_count": lead_count,
    }
    updates: dict[str, Any] = {
        "status": "completed",
        "completed_at": _now(),
        "updated_at": _now(),
        "summary": summary,
        "provider_provenance": providers,
    }
    try:
        client = get_supabase_client()
        client.table("discoveries").update(updates).eq("id", discovery_id).execute()
        _log(
            f"finalized discovery {discovery_id}: "
            f"{company_count} companies / {lead_count} leads"
        )
        return True
    except Exception as e:
        _log(f"finalize_discovery update error: {e}")
        await asyncio.to_thread(
            mark_discovery_status, discovery_id, "failed", str(e)
        )
        return False


def _link_leads(
    discovery_id: str, leads: list[dict], ws_lead_ids: list[str]
) -> Optional[int]:
    """Persist discovery_leads links (one per normalized lead, ranked)."""
    if not discovery_id or not ws_lead_ids:
        return 0
    client = get_supabase_client()
    if not client:
        return None
    try:
        rows = [
            {
                "discovery_id": discovery_id,
                "lead_id": ws_lead_ids[i],
                "rank": i + 1,
                "match_score": _match_score(leads[i]),
                "source_provider": str(
                    leads[i].get("provider") or leads[i].get("source") or "search"
                ),
            }
            for i in range(len(ws_lead_ids))
        ]
        client.table("discovery_leads").insert(rows).execute()
        return len(rows)
    except Exception as e:
        _log(f"_link_leads error: {e}")
        return None


def _link_companies(
    discovery_id: str, workspace_id: str, ws_lead_ids: list[str]
) -> Optional[int]:
    """Link every distinct company behind the surfaced leads.

    Companies are never duplicated: one canonically deduplicated company per
    domain (007), one workspace_companies row per (workspace, company), and
    one discovery_companies row per (discovery, company).
    """
    if not discovery_id or not workspace_id or not ws_lead_ids:
        return 0
    client = get_supabase_client()
    if not client:
        return None
    try:
        wl_result = (
            client.table("workspace_leads")
            .select("company_id, source")
            .in_("id", ws_lead_ids)
            .not_.is_("company_id", "null")
            .execute()
        )
        company_sources: dict[str, str] = {}
        for r in getattr(wl_result, "data", None) or []:
            cid = r.get("company_id")
            if not cid:
                continue
            current = company_sources.get(str(cid), "")
            if not current:
                company_sources[str(cid)] = str(r.get("source") or "").strip()
        company_ids = {
            r["company_id"]
            for r in (getattr(wl_result, "data", None) or [])
            if r.get("company_id")
        }
        if not company_ids:
            return 0

        wc_result = (
            client.table("workspace_companies")
            .select("id, company_id")
            .eq("workspace_id", workspace_id)
            .in_("company_id", list(company_ids))
            .execute()
        )
        wc_by_company: dict[str, list[str]] = {}
        for r in getattr(wc_result, "data", None) or []:
            cid = r.get("company_id")
            if cid:
                wc_by_company.setdefault(str(cid), []).append(str(r["id"]))

        rows = []
        rank = 0
        for company_id in sorted(company_ids):
            wc_ids = wc_by_company.get(str(company_id)) or []
            if not wc_ids:
                continue
            rank += 1
            provider = company_sources.get(str(company_id), "")
            rows.append({
                "discovery_id": discovery_id,
                "workspace_company_id": wc_ids[0],
                "company_id": company_id,
                "rank": rank,
                "match_score": 0,
                "source_provider": provider,
            })
            if provider:
                try:
                    client.table("companies").update(
                        {"source_provider": provider}
                    ).eq("id", company_id).is_("source_provider", "").execute()
                except Exception as e:
                    _log(f"_link_companies provenance backfill skipped for {company_id}: {e}")
        if not rows:
            return 0
        client.table("discovery_companies").insert(rows).execute()
        return len(rows)
    except Exception as e:
        _log(f"_link_companies error: {e}")
        return None


def _merge_metadata(discovery_id: str, patch: dict) -> bool:
    """Read-merge-write one discovery's ``metadata`` JSONB column.

    The row already stores ``plan`` and the live ``progress`` tick; both
    writers go through here so neither clobbers the other.
    """
    client = get_supabase_client()
    if not client or not discovery_id:
        return False
    try:
        result = (
            client.table("discoveries")
            .select("metadata")
            .eq("id", discovery_id)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        if not rows:
            _log(f"_merge_metadata skipped: discovery {discovery_id} was not found")
            return False
        raw_metadata = rows[0].get("metadata") or {}
        if isinstance(raw_metadata, str):
            try:
                raw_metadata = json.loads(raw_metadata)
            except (TypeError, ValueError):
                raw_metadata = {}
        metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        for key, value in patch.items():
            metadata[key] = value
        update_result = client.table("discoveries").update(
            {"metadata": metadata, "updated_at": _now()}
        ).eq("id", discovery_id).execute()
        _log(
            f"_merge_metadata update discovery={discovery_id} "
            f"patch_keys={sorted(patch)} response_rows={len(getattr(update_result, 'data', None) or [])}"
        )

        # Supabase update responses may omit row data. Verify the canonical
        # row so a silent metadata write cannot report success.
        verify = client.table("discoveries").select("metadata").eq("id", discovery_id).limit(1).execute()
        verify_rows = getattr(verify, "data", None) or []
        verify_metadata = verify_rows[0].get("metadata") if verify_rows else {}
        if isinstance(verify_metadata, str):
            try:
                verify_metadata = json.loads(verify_metadata)
            except (TypeError, ValueError):
                verify_metadata = {}
        verified_keys = set(verify_metadata) if isinstance(verify_metadata, dict) else set()
        missing = sorted(set(patch) - verified_keys)
        if missing:
            _log(
                f"_merge_metadata verification failed discovery={discovery_id} "
                f"missing_keys={missing}; retrying merged metadata write"
            )
            client.table("discoveries").update(
                {"metadata": metadata, "updated_at": _now()}
            ).eq("id", discovery_id).execute()
            return False
        return True
    except Exception as e:
        _log(f"_merge_metadata error: {e}")
        return False


def store_discovery_plan(
    discovery_id: str,
    plan: dict,
    context_provenance: dict | None = None,
) -> bool:
    """Persist the derived Discovery Plan onto ``discoveries.metadata.plan``.

    Called from the search workflow once the plan is derived, so the plan
    exists before the first live stage is visible to the UI. Idempotent.
    """
    if not discovery_id or not plan:
        return False
    patch = {"plan": plan}
    if isinstance(context_provenance, dict):
        patch["context_provenance"] = context_provenance
    if not _merge_metadata(discovery_id, patch):
        return False
    _log(f"stored plan on discovery {discovery_id}")
    return True


def store_discovery_context(discovery_id: str, provenance: dict) -> bool:
    """Persist context provenance alongside the existing discovery plan."""
    if not discovery_id or not isinstance(provenance, dict):
        return False
    if not _merge_metadata(discovery_id, {"context_provenance": provenance}):
        return False
    _log(f"stored context provenance on discovery {discovery_id}")
    return True


def update_discovery_progress(discovery_id: str, stage: str, progress: int) -> bool:
    """Persist the live execution tick (stage label + percent) onto metadata."""
    if not discovery_id:
        return False
    _merge_metadata(discovery_id, {"progress": {"stage": stage, "progress": progress}})
    return True


def _match_score(lead: dict) -> float:
    raw = lead.get("relevance_score") or lead.get("score") or lead.get("match_score")
    if isinstance(raw, (int, float)):
        return round(float(raw if raw > 1 else raw * 100), 1)
    return 0.0
