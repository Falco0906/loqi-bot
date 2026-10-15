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
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from services.job_engine import job_manager
from services.platform.supabase import get_supabase_client
from services.workspace.lead_projection import workspace_lead_context

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


class DiscoveryJobLifecycleError(Exception):
    """A durable Discovery search could not be accepted for execution."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class DiscoveryLeadDecisionError(Exception):
    """A selected Discovery lead could not be durably updated."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _count_of(payload: Any) -> int:
    try:
        return int(payload[0]["count"])
    except Exception:
        return 0


async def decide_discovery_lead(
    owner_id: str,
    workspace_id: str,
    session_token: str,
    lead: dict[str, Any],
    approved: bool,
) -> dict[str, Any]:
    """Persist one Discovery-card approval or rejection for its workspace lead.

    The browser supplies the canonical ``workspace_leads.id`` carried by a
    durable Discovery detail response.  The persistence boundary verifies
    that it belongs to ``workspace_id`` before changing its lifecycle status.
    """
    lead = dict(lead)
    lead_id = str(lead.get("id") or "").strip()
    if not lead_id:
        raise DiscoveryLeadDecisionError(400, "Lead identity is required")

    from services.workspace.state import persist_lead_decision_awaited

    canonical_lead_id = await persist_lead_decision_awaited(
        owner_id,
        lead,
        approved,
        workspace_id=workspace_id,
    )
    if not canonical_lead_id:
        raise DiscoveryLeadDecisionError(503, "Lead decision could not be persisted")

    # Preserve the legacy projection emission. Durable workspace_leads status
    # remains the decision authority.
    from services.world_model.events import EventType
    from services.world_model.publisher import publish

    publish(
        session_token,
        EventType.LEAD_SELECTED if approved else EventType.LEAD_DISCOVERED,
        {
            "lead_id": str(canonical_lead_id),
            "name": lead.get("name", lead.get("company", "")),
            "approved": approved,
        },
        actor="user",
    )
    return {"ok": True, "lead": lead, "approved": approved}


def create_discovery(
    workspace_id: str,
    user_id: str,
    query: str,
    title: Optional[str] = None,
    ui_filters: dict[str, str] | None = None,
    search_scope: str = "provider",
) -> Optional[dict]:
    """Persist a new discovery row (no job link yet).

    Called synchronously (via ``asyncio.to_thread``) BEFORE the search job is
    enqueued. The caller then creates the job with ``discovery_id`` so the
    relationship lives on the job side (``jobs.discovery_id``). Status starts
    at ``searching``; ``finalize_discovery`` moves it to ``completed``/
    ``failed`` using the job's outcome.

    Creation defaults (everything else stays empty/false):
    ``title = title or query``, ``last_viewed_at = created_at``, and
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
        "title": str(title or query or ""),
        "last_viewed_at": now,
        "last_refreshed_at": now,
        "summary": {},
        "metadata": {"search_scope": search_scope, **({"ui_filters": ui_filters} if ui_filters else {})},
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


async def create_search_run(
    user_id: str,
    query: str,
    session_token: str = "",
    *,
    display_title: str | None = None,
    workspace_id: str = "",
    on_update=None,
    initiation: Literal["manual", "automated"] = "automated",
    ui_filters: dict[str, str] | None = None,
) -> dict:
    """Create a durable Discovery, then schedule its linked search job.

    Discovery is the ownership root for every search job. The durable row is
    written before the job is scheduled, and the worker receives that exact
    ``discovery_id`` for progress, failure, recovery, and finalization.
    """
    from services.capabilities.beta import beta_feature_enabled, beta_feature_unavailable_message

    # Manual Beta searches read only the selected workspace's saved leads.
    # Provider acquisition remains behind the disabled sourcing capability.
    required_capability = (
        "lead_search" if initiation == "manual" else "autonomous_lead_sourcing"
    )
    if not beta_feature_enabled(required_capability):
        raise DiscoveryJobLifecycleError(
            403,
            beta_feature_unavailable_message(required_capability),
        )

    if initiation == "manual" and not workspace_id:
        raise DiscoveryJobLifecycleError(400, "Select an authorized workspace before searching")
    if not workspace_id:
        from services.workspace.state import ensure_workspace

        workspace_id = await asyncio.to_thread(ensure_workspace, user_id) or ""

    _log(
        "[kickoff] create_search_run: "
        f"user={user_id} query={query!r} workspace_id={workspace_id or '(none)'}"
    )
    discovery = None
    if workspace_id:
        discovery = await asyncio.to_thread(
            create_discovery,
            workspace_id,
            user_id,
            query,
            display_title,
            search_scope="workspace" if initiation == "manual" else "provider",
            **({"ui_filters": ui_filters} if ui_filters else {}),
        )
    discovery_id = str((discovery or {}).get("id") or "")
    if not discovery_id:
        raise DiscoveryJobLifecycleError(503, "Discovery could not be persisted")

    async def emit_job_event(payload: dict) -> None:
        try:
            from services.events.bus import event_bus

            event_type = (
                "job.completed"
                if payload.get("status") in ("completed", "failed", "cancelled")
                else "job.progress"
            )
            data: dict = {
                "stage": payload.get("stage", ""),
                "discovery_id": discovery_id,
            }
            if payload.get("error"):
                data["error"] = str(payload.get("error"))[:200]
            if payload.get("error_kind"):
                data["error_kind"] = str(payload.get("error_kind"))[:40]
            await event_bus.publish_user_event(
                user_id,
                event_type,
                data,
                job_id=payload.get("job_id", ""),
                status=str(payload.get("status") or ""),
                progress=int(payload.get("progress") or 0),
            )
        except Exception:
            # Redis fan-out is a projection. Durable Discovery/job state is
            # already written by the runner and remains authoritative.
            pass

    def handle_update(payload: dict) -> None:
        status = payload.get("status")
        job_id = str(payload.get("job_id") or "")
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(emit_job_event(payload))
        except RuntimeError:
            pass

        if status in ("failed", "cancelled"):
            linked_discovery = get_discovery_by_job_id(job_id)
            # Finalization may already have recorded a detailed terminal
            # summary (provider count, canonical count, and safe failure
            # category). Do not replace that durable diagnosis with the
            # runner's generic failure wrapper.
            if linked_discovery and str(linked_discovery.get("status") or "") not in (
                "completed", "failed", "cancelled",
            ):
                mark_discovery_status(
                    str(linked_discovery["id"]),
                    str(status),
                    str(payload.get("error") or ""),
                    error_kind=str(payload.get("error_kind") or ""),
                )
        elif status == "running" and payload.get("stage"):
            linked_discovery_id = get_discovery_id_for_job(job_id)
            if linked_discovery_id:
                update_discovery_progress(
                    linked_discovery_id,
                    str(payload["stage"]),
                    int(payload.get("progress") or 0),
                )

        if on_update:
            try:
                on_update(payload)
            except Exception as error:
                _log(f"external search-job update callback failed: {error}")

    result = await job_manager.create_search_job(
        user_id=user_id,
        query=query,
        discovery_id=discovery_id,
        workspace_id=workspace_id,
        search_scope="workspace" if initiation == "manual" else "provider",
        on_update=handle_update,
        on_complete=finalize_discovery,
    )
    if not result:
        await asyncio.to_thread(
            mark_discovery_status,
            discovery_id,
            "failed",
            "Failed to create job",
        )
        raise DiscoveryJobLifecycleError(500, "Failed to create job")

    if session_token:
        try:
            from services.world_model import EventType as WMEventType, publish

            publish(
                session_token,
                WMEventType.LEAD_DISCOVERED,
                {
                    "job_id": result.get("job_id", ""),
                    "discovery_id": discovery_id,
                    "query": query,
                    "status": "searching",
                },
                actor="user",
            )
        except Exception as error:
            _log(f"publish(LEAD_DISCOVERED) failed (non-fatal): {error}")

    return {**result, "discovery_id": discovery_id}


async def get_job_for_user(job_id: str, user_id: str) -> Optional[dict]:
    """Return one job only when it belongs to the authenticated user."""
    job = await asyncio.to_thread(job_manager.get_job, job_id)
    if not job or str(job.get("user_id") or "") != str(user_id):
        return None
    return job


async def get_job_results_for_user(job_id: str, user_id: str) -> Optional[dict]:
    """Return completed job results only when the job belongs to the user."""
    job = await get_job_for_user(job_id, user_id)
    if not job:
        return None
    return await asyncio.to_thread(job_manager.get_job_results, job_id)


async def list_recent_jobs_for_user(user_id: str) -> list[dict]:
    """Return recent durable jobs for the authenticated user only."""
    return await asyncio.to_thread(job_manager.list_recent_jobs, user_id)


STALE_SEARCH_JOB_GRACE_SECONDS = 300


async def reconcile_stale_search_jobs() -> int:
    """Reconcile durable search jobs interrupted by a process restart.

    Jobs with persisted results are finalized against their linked Discovery;
    jobs without results become an explicit failed job and failed Discovery.
    A second pass repairs terminal jobs whose Discovery was not finalized
    before the process stopped. Every operation is idempotent.
    """
    from services.job_engine.models import JobStatus
    from services.job_engine.storage import JobStorage

    client = get_supabase_client()
    if client is None:
        return 0

    def chunks(values: list[str], size: int = 100) -> list[list[str]]:
        return [values[index : index + size] for index in range(0, len(values), size)]

    storage = JobStorage()
    grace_iso = (
        datetime.now(timezone.utc) - timedelta(seconds=STALE_SEARCH_JOB_GRACE_SECONDS)
    ).isoformat()
    recovered = 0

    try:
        rows = await asyncio.to_thread(
            lambda: (
                client.table("jobs")
                .select("id, discovery_id")
                .eq("type", "search")
                .in_("status", ["queued", "running"])
                .lt("updated_at", grace_iso)
                .execute()
            )
        )
        orphaned = getattr(rows, "data", None) or []
    except Exception as error:
        _log(f"stale search job scan failed: {error}")
        orphaned = []

    orphan_ids = [str(row.get("id")) for row in orphaned if row.get("id")]
    jobs_with_results: set[str] = set()
    for job_ids in chunks(orphan_ids):
        try:
            result_rows = await asyncio.to_thread(
                lambda: (
                    client.table("search_results")
                    .select("job_id")
                    .in_("job_id", job_ids)
                    .execute()
                )
            )
            jobs_with_results.update(
                str(row.get("job_id"))
                for row in (result_rows.data or [])
                if row.get("job_id")
            )
        except Exception as error:
            _log(f"search results batch lookup failed: {error}")

    orphan_discovery_ids = [
        str(row.get("discovery_id")) for row in orphaned if row.get("discovery_id")
    ]
    orphan_discovery_status: dict[str, str] = {}
    for discovery_ids in chunks(orphan_discovery_ids):
        try:
            discovery_rows = await asyncio.to_thread(
                lambda: (
                    client.table("discoveries")
                    .select("id, status")
                    .in_("id", discovery_ids)
                    .execute()
                )
            )
            orphan_discovery_status.update({
                str(row.get("id")): str(row.get("status"))
                for row in (discovery_rows.data or [])
            })
        except Exception as error:
            _log(f"orphan discoveries batch lookup failed: {error}")

    for row in orphaned:
        job_id = str(row.get("id") or "")
        if not job_id:
            continue
        try:
            if job_id in jobs_with_results:
                job = await asyncio.to_thread(storage.get_job, job_id)
                finalized = bool(job and await finalize_discovery(job))
                if finalized:
                    await asyncio.to_thread(
                        storage.update_job,
                        job_id,
                        status=JobStatus.COMPLETED,
                        stage="Complete",
                        progress=100,
                        result_ready=True,
                        completed_at=datetime.now(timezone.utc),
                    )
                    _log(f"finalized orphaned search job {job_id}")
                else:
                    await asyncio.to_thread(
                        storage.update_job,
                        job_id,
                        status=JobStatus.FAILED,
                        stage="Failed",
                        error_message="Discovery results could not be persisted after restart",
                        completed_at=datetime.now(timezone.utc),
                    )
                    _log(f"orphaned search job {job_id} failed finalization")
            else:
                reason = "Search run interrupted by restart"
                await asyncio.to_thread(
                    storage.update_job,
                    job_id,
                    status=JobStatus.FAILED,
                    stage="Failed",
                    error_message=reason,
                    completed_at=datetime.now(timezone.utc),
                )
                discovery_id = str(row.get("discovery_id") or "")
                if orphan_discovery_status.get(discovery_id) == "searching":
                    await asyncio.to_thread(
                        mark_discovery_status,
                        discovery_id,
                        "failed",
                        reason,
                    )
                _log(f"failed orphaned search job {job_id}")
            recovered += 1
        except Exception as error:
            _log(f"stale search job {job_id} reconcile failed: {error}")

    try:
        rows = await asyncio.to_thread(
            lambda: (
                client.table("jobs")
                .select("id, status, error_message, discovery_id")
                .eq("type", "search")
                .in_("status", ["completed", "failed"])
                .not_.is_("discovery_id", "null")
                .order("created_at", desc=True)
                .limit(200)
                .execute()
            )
        )
        terminal_jobs = getattr(rows, "data", None) or []
    except Exception as error:
        _log(f"terminal search job scan failed: {error}")
        terminal_jobs = []

    terminal_discovery_ids = [
        str(row.get("discovery_id")) for row in terminal_jobs if row.get("discovery_id")
    ]
    discoveries_by_id: dict[str, dict] = {}
    for discovery_ids in chunks(terminal_discovery_ids):
        try:
            discovery_rows = await asyncio.to_thread(
                lambda: (
                    client.table("discoveries")
                    .select("id, status")
                    .in_("id", discovery_ids)
                    .execute()
                )
            )
            for discovery in discovery_rows.data or []:
                discoveries_by_id[str(discovery.get("id"))] = discovery
        except Exception as error:
            _log(f"terminal discoveries batch lookup failed: {error}")

    for row in terminal_jobs:
        job_id = str(row.get("id") or "")
        try:
            discovery = discoveries_by_id.get(str(row.get("discovery_id") or ""))
            if not discovery or discovery.get("status") != "searching":
                continue
            if row.get("status") == JobStatus.COMPLETED.value:
                job = await asyncio.to_thread(storage.get_job, job_id)
                if job and await finalize_discovery(job):
                    _log(f"finalized completed search job {job_id}")
                    recovered += 1
                elif job:
                    await asyncio.to_thread(
                        storage.update_job,
                        job_id,
                        status=JobStatus.FAILED,
                        stage="Failed",
                        error_message="Discovery results could not be persisted after restart",
                        completed_at=datetime.now(timezone.utc),
                    )
                    _log(f"completed search job {job_id} failed finalization")
                    recovered += 1
            elif row.get("status") == JobStatus.FAILED.value:
                await asyncio.to_thread(
                    mark_discovery_status,
                    str(discovery["id"]),
                    "failed",
                    row.get("error_message") or "Search run failed",
                )
                _log(f"failed terminal search job {job_id}")
                recovered += 1
        except Exception as error:
            _log(f"terminal search job {job_id} reconcile failed: {error}")
    return recovered


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


def get_discovery(discovery_id: str, workspace_id: str = "", *, strict: bool = False) -> Optional[dict]:
    """Full discovery detail: row + surfaced companies + leads (joined).

    When ``workspace_id`` is supplied (request path), the lookup is constrained
    to that workspace so a foreign discovery id cannot return another tenant's
    PII. Internal/worker callers may omit it (trusted, server-derived ids).
    Context readers use ``strict`` to distinguish missing rows from outages.
    """
    client = get_supabase_client()
    if not client:
        if strict:
            raise RuntimeError("Discovery context persistence is unavailable")
        return None
    try:
        query = (
            client.table("discoveries")
            .select(
                f"{_DISCOVERY_SELECT}, "
                "discovery_companies(rank, match_score, "
                "company_id), "
                "discovery_leads(rank, match_score, status, source_provider, "
                "lead_id, workspace_lead:workspace_leads("
                "id, workspace_id, deleted_at, company_id, email, first_name, last_name, title, phone, "
                "linkedin_url, lead_status, source, metadata))"
            )
            .eq("id", discovery_id)
        )
        if workspace_id:
            query = query.eq("workspace_id", workspace_id)
        result = query.is_("deleted_at", "null").limit(1).execute()
        if strict and not isinstance(getattr(result, "data", None), list):
            raise RuntimeError("Discovery context read returned invalid data")
        rows = getattr(result, "data", None) or []
        if not rows:
            return None
        return _workspace_discovery_results(rows[0])
    except Exception as e:
        if strict:
            raise
        _log(f"get_discovery error: {e}")
        return None


def _workspace_discovery_results(row: dict) -> dict:
    """Expose only facts acquired in the Discovery's own workspace.

    Discovery links do not establish ownership of a global company/person
    payload. Build the compatible company projection from local lead context.
    Reject foreign or deleted nested links, even if old stored links are bad.
    """
    row = dict(row)
    leads = []
    companies = {}
    for link in row.get("discovery_leads") or []:
        lead = link.get("workspace_lead") or {}
        if lead.get("workspace_id") != row.get("workspace_id") or lead.get("deleted_at"):
            continue
        lead = {key: value for key, value in lead.items() if key != "lead"}
        leads.append({**link, "workspace_lead": lead})
        if lead.get("company_id"):
            context = workspace_lead_context(lead)
            companies[lead["company_id"]] = {
                "id": lead["company_id"], **context, "name": context.get("company", ""),
            }
    row["discovery_leads"] = leads
    row["discovery_companies"] = [
        {**link, "company": companies[link["company_id"]]}
        for link in row.get("discovery_companies") or []
        if link.get("company_id") in companies
    ]
    return row


def get_discovery_lead_provenance(
    discovery_id: str,
    workspace_id: str,
) -> dict[str, list[str]]:
    """Return provider provenance for canonical leads in one scoped run.

    Discovery owns per-run provider provenance.  The Lead Database can use
    this read-only projection to include an explicit provider search in its
    canonical, paginated workspace-lead result set without trusting a client
    supplied lead ID or creating a second result store.
    """
    if not discovery_id or not workspace_id:
        return {}
    client = get_supabase_client()
    if not client:
        raise RuntimeError("Discovery persistence is unavailable")
    try:
        result = (
            client.table("discoveries")
            .select("discovery_leads(lead_id, source_provider)")
            .eq("id", discovery_id)
            .eq("workspace_id", workspace_id)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", None)
        if not isinstance(rows, list):
            raise ValueError("Invalid Discovery provenance response")
        links = rows[0].get("discovery_leads", []) if rows else []
        provenance: dict[str, list[str]] = {}
        for link in links if isinstance(links, list) else []:
            if not isinstance(link, dict):
                continue
            lead_id = str(link.get("lead_id") or "").strip()
            source = str(link.get("source_provider") or "").strip()
            if not lead_id:
                continue
            values = provenance.setdefault(lead_id, [])
            if source and source not in values:
                values.append(source)
        return provenance
    except Exception as error:
        # A Discovery projection is optional for lead browsing.  Its failure
        # must not make canonical workspace leads unreadable.
        _log(
            "get_discovery_lead_provenance error: "
            f"{type(error).__name__}"
        )
        raise


def mark_discovery_status(
    discovery_id: str,
    status: str,
    error: str = "",
    *,
    error_kind: str = "",
) -> bool:
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
            if error_kind:
                summary["error_kind"] = error_kind[:40]
            updates["summary"] = summary
        if status in ("completed", "failed", "cancelled"):
            updates["completed_at"] = _now()
        client.table("discoveries").update(updates).eq("id", discovery_id).execute()
        return True
    except Exception as e:
        _log(f"mark_discovery_status error: {e}")
        return False


async def search_saved_workspace_leads(job, on_progress) -> dict:
    """Run manual Discovery over authorized, already-persisted workspace rows.

    Reuse the durable search job/staging/finalization contract. Staging holds
    canonical IDs, never provider records to import. Interpret prospect intent
    and qualify deterministically, with no model or provider sourcing calls.
    """
    from services.job_engine.storage import JobStorage, SearchResultPersistenceError
    from services.leads.service import list_workspace_leads
    from services.workspace.access import resolve_workspace_context
    from services.discovery.context import retrieve_discovery_context
    from services.discovery.plan import derive_discovery_plan, icp_from_plan, prospect_match_outcome
    from services.discovery.qualification import score_lead
    from services.persistence.launch import WorkspaceLeadRepository
    from services.workspace.lead_projection import workspace_lead_fields

    if not job.workspace_id or not job.query.strip():
        raise ValueError("A workspace and search query are required")
    await asyncio.to_thread(resolve_workspace_context, None, job.user_id, job.workspace_id)
    discovery = await asyncio.to_thread(get_discovery, job.discovery_id, job.workspace_id, strict=True)
    if not discovery or discovery.get("created_by") != job.user_id:
        raise ValueError("Search is unavailable in this workspace")
    metadata = discovery.get("metadata") or {}
    filters = metadata.get("ui_filters") or {}
    await asyncio.to_thread(on_progress, job.id, "Understanding target market", 10)
    context = await retrieve_discovery_context(job.user_id, query=job.query, workspace_id=job.workspace_id)
    plan = await asyncio.to_thread(derive_discovery_plan, job.query, existing_context=context, prospect_search=True)
    plan_dict = plan.to_dict()
    if not await asyncio.to_thread(store_discovery_plan, job.discovery_id, plan_dict, context.get("provenance") or {}):
        raise SearchResultPersistenceError("Interpreted search criteria could not be saved")
    await asyncio.to_thread(on_progress, job.id, "Finding matching companies", 40)
    result = await list_workspace_leads(job.workspace_id, "", page_size=None, filters=filters, include_outcomes=True)
    outcomes = result["candidate_outcomes"]
    outcomes["evaluated_count"] = len(result["leads"])
    decisions = {}
    matches = []
    for lead in result["leads"]:
        decision = prospect_match_outcome(lead, plan_dict["search_constraints"])
        decisions[lead["id"]] = decision
        if decision["matched"]:
            matches.append(lead)
        else:
            reason = decision["reason"]
            outcomes["exclusions"][reason] = outcomes["exclusions"].get(reason, 0) + 1
    outcomes["matched_count"] = len(matches)
    outcomes["unverified_match_count"] = sum(bool(decisions[lead["id"]]["unverified_fields"]) for lead in matches)
    outcomes["interpretation_status"] = (plan_dict.get("search_constraints") or {}).get("interpretation_status", "unknown")
    # Retain measured outcomes even if a later assessment/staging write fails.
    job.result = {**(job.result or {}), "candidate_outcomes": outcomes}
    if not await asyncio.to_thread(_merge_metadata, job.discovery_id, {"candidate_outcomes": outcomes}):
        raise SearchResultPersistenceError("Search candidate outcomes could not be saved")
    await asyncio.to_thread(on_progress, job.id, "Ranking prospects", 65)
    icp = icp_from_plan(plan_dict)
    repository = WorkspaceLeadRepository()
    staged = []
    # Qualification is existing canonical workspace metadata, not shared global
    # enrichment. No per-lead model/provider call, and no selected-lead generation.
    async def assess_lead(lead):
        saved = await repository.get_for_workspace(lead["id"], job.workspace_id)
        if saved is None or saved.deleted_at is not None:
            raise SearchResultPersistenceError("A matching lead is no longer available in this workspace")
        fields = workspace_lead_fields(saved)
        qualification = score_lead({**fields, "name": f"{fields['first_name']} {fields['last_name']}".strip()}, icp, context)
        qualification["search_match"] = {"unverified_fields": decisions[lead["id"]]["unverified_fields"]}
        metadata = {**(saved.metadata or {}), "qualification": qualification}
        if not await repository.update_qualification_for_workspace(saved.id, job.workspace_id, metadata):
            raise SearchResultPersistenceError("A matching lead's assessment could not be saved")
        return {"workspace_lead_id": saved.id, "id": saved.id, "source": "lead_database",
                "commercial_score": qualification["final_score"]}

    for start in range(0, len(matches), 4):
        staged.extend(await asyncio.gather(*(assess_lead(lead) for lead in matches[start:start + 4])))
    staged.sort(key=lambda lead: (-lead["commercial_score"], lead["id"]))
    if not await asyncio.to_thread(JobStorage().store_search_results, job.id, staged):
        raise SearchResultPersistenceError("Saved search results could not be recorded")
    await asyncio.to_thread(on_progress, job.id, "Preparing recommendations", 90)
    return {"ok": True, "result": {"search_scope": "workspace", "matched_lead_count": len(staged),
                                   "candidate_outcomes": outcomes}}


async def finalize_discovery(job) -> bool:
    """Move a discovery to ``completed`` using its job's stored results.

    Called from the runner's ``on_complete`` hook (event loop context).
    Idempotent for completed runs. Confirmed staged rows are retained even
    when another batch failed, but unavailable staging can never mean zero.
    """
    try:
        discovery_id = str(getattr(job, "discovery_id", "") or "")
        _log(f"[kickoff] finalize_discovery entered: job={getattr(job, 'id', '')} discovery_id={discovery_id or '(empty, resolving via job FK)'}")
        row = None
        if discovery_id:
            client = get_supabase_client()
            try:
                result = await asyncio.to_thread(
                    lambda: (
                        client.table("discoveries")
                        .select(_DISCOVERY_SELECT)
                        .eq("id", discovery_id)
                        .limit(1)
                        .execute()
                    )
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

        from services.capabilities.beta import beta_feature_enabled
        workspace_search = (getattr(job, "payload", None) or {}).get("search_scope") == "workspace"
        if getattr(job, "workspace_id", "") and job.workspace_id != workspace_id:
            raise ValueError("Search workspace does not match its Discovery")
        if row.get("deleted_at"):
            return False
        if not workspace_search and not beta_feature_enabled("autonomous_lead_sourcing"):
            await asyncio.to_thread(mark_discovery_status, discovery_id, "failed",
                                   "Provider sourcing is disabled. Search your saved workspace leads.",
                                   error_kind="permanent")
            return False

        from services.job_engine.storage import JobStorage
        leads = await asyncio.to_thread(JobStorage().get_search_results, job.id)
        _log(f"[kickoff] finalize_discovery: search_results={len(leads) if leads else 0} for job {getattr(job, 'id', '')}")

        from services.workspace.state import _normalization_lock_key, _normalize_lead

        ws_lead_ids: list[str] = []
        normalized_leads: list[dict] = []
        seen: set[str] = set()
        providers: dict[str, int] = {}
        normalization_errors: list[str] = []
        skipped_records = 0
        unique_leads: list[dict] = []
        source_keys: set[str] = set()
        for lead in leads:
            provider = str(lead.get("provider") or lead.get("source") or "search")
            providers[provider] = providers.get(provider, 0) + 1
            email = str(lead.get("email") or "").strip().lower()
            fallback = str(lead.get("lead_id") or lead.get("id") or lead.get("linkedin_url") or "").strip().lower()
            # Collapse duplicates within a source, but let each source reach
            # canonical normalization so its durable provenance is retained.
            source_key = f"{provider}:{email or fallback}" if email or fallback else ""
            if source_key and source_key in source_keys:
                continue
            if source_key:
                source_keys.add(source_key)
            unique_leads.append(lead)

        # Canonical normalization performs several repository round trips per
        # lead. Bound parallelism avoids a 30-lead serial tail, while the
        # per-identity lock prevents multiple contacts at the same provider
        # company from racing the global company/workspace-company unique
        # indexes. CSV imports are sequential and never had this race.
        semaphore = asyncio.Semaphore(4)
        normalization_locks: dict[str, asyncio.Lock] = {}

        async def normalize_one(lead: dict) -> str | Exception | None:
            if workspace_search:
                from services.persistence.launch import WorkspaceLeadRepository
                async with semaphore:
                    saved = await WorkspaceLeadRepository().get_for_workspace(
                        str(lead.get("workspace_lead_id") or ""), workspace_id,
                    )
                if saved is None or saved.deleted_at is not None:
                    return ValueError("A saved lead is no longer available in this workspace")
                return saved.id
            identity = _normalization_lock_key(lead)
            if identity is None:
                return None
            lock = normalization_locks.setdefault(identity, asyncio.Lock())
            async with lock:
                async with semaphore:
                    try:
                        return await _normalize_lead(workspace_id, lead)
                    except Exception as error:
                        return error

        normalized_ids = await asyncio.gather(
            *(normalize_one(lead) for lead in unique_leads),
        )
        for lead, normalized in zip(unique_leads, normalized_ids):
            if isinstance(normalized, Exception):
                _log(f"finalize_discovery normalize lead failed: {normalized}")
                normalization_errors.append(str(normalized))
                continue
            ws_lead_id = normalized
            if ws_lead_id and ws_lead_id not in seen:
                seen.add(ws_lead_id)
                ws_lead_ids.append(ws_lead_id)
                normalized_leads.append(lead)
            elif not ws_lead_id:
                # A provider row without email/domain/provider identity cannot
                # be linked to a canonical lead safely. It is a bad record,
                # not evidence that the persistence system failed.
                skipped_records += 1
    except Exception as e:
        _log(f"finalize_discovery failed: {e}")
        if row:
            await asyncio.to_thread(
                mark_discovery_status,
                str(row["id"]),
                "failed",
                str(e),
                error_kind="persistence",
            )
        return False

    candidate_outcomes = None
    if workspace_search:
        candidate_outcomes = ((getattr(job, "result", None) or {}).get("candidate_outcomes")
                              or (row.get("metadata") or {}).get("candidate_outcomes"))
        if candidate_outcomes is not None:
            # Matching, staging and canonical linking are different stages.
            # A missing/truncated stage must not become a completed zero search.
            matched = candidate_outcomes.get("matched_count")
            if matched != len(leads) or matched != len(ws_lead_ids):
                normalization_errors.append("Search candidate counts do not match staged canonical results")

    linked = await asyncio.to_thread(_link_leads, discovery_id, normalized_leads, ws_lead_ids)
    companies_linked = await asyncio.to_thread(
        _link_companies, discovery_id, workspace_id, ws_lead_ids
    )

    staging = (getattr(job, "result", None) or {}).get("search_staging") or {}
    if staging.get("failed_batches") or normalization_errors or linked is None or companies_linked is None:
        reasons = normalization_errors[:3]
        if staging.get("failed_batches"):
            reasons.append("Some provider results could not be staged")
        if linked is None:
            reasons.append("Discovery lead links could not be persisted")
        if companies_linked is None:
            reasons.append("Discovery company links could not be persisted")
        error = "; ".join(reasons) or "Discovery persistence failed"
        summary = {
            "error": error,
            "error_kind": "persistence",
            "provider_lead_count": staging.get("provider_lead_count", len(leads)),
            "persisted_lead_count": len(ws_lead_ids),
            "skipped_provider_record_count": skipped_records,
            "persistence": "partial_failed" if ws_lead_ids else "failed",
            "staged_lead_count": len(leads),
            "failed_staging_batches": staging.get("failed_batches", 0),
        }
        if workspace_search:
            summary["candidate_outcomes"] = candidate_outcomes
        await asyncio.to_thread(
            mark_discovery_status,
            discovery_id,
            "failed",
            error,
            error_kind="persistence",
        )
        try:
            client = get_supabase_client()
            await asyncio.to_thread(
                lambda: client.table("discoveries")
                .update({"summary": summary})
                .eq("id", discovery_id)
                .execute()
            )
        except Exception:
            pass
        return False

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
        "provider_lead_count": len(leads),
        "skipped_provider_record_count": skipped_records,
    }
    if workspace_search:
        summary["candidate_outcomes"] = candidate_outcomes
    updates: dict[str, Any] = {
        "status": "completed",
        "completed_at": _now(),
        "updated_at": _now(),
        "summary": summary,
        "provider_provenance": providers,
    }
    try:
        client = get_supabase_client()
        await asyncio.to_thread(
            lambda: client.table("discoveries")
            .update(updates)
            .eq("id", discovery_id)
            .execute()
        )
        _log(
            f"finalized discovery {discovery_id}: "
            f"{company_count} companies / {lead_count} leads"
        )
        return True
    except Exception as e:
        _log(f"finalize_discovery update error: {e}")
        await asyncio.to_thread(
            mark_discovery_status,
            discovery_id,
            "failed",
            str(e),
            error_kind="persistence",
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
            .eq("workspace_id", workspace_id)
            .is_("deleted_at", "null")
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
    return _merge_metadata(discovery_id, {"progress": {"stage": stage, "progress": progress}})


def _match_score(lead: dict) -> float:
    raw = lead.get("relevance_score") or lead.get("score") or lead.get("match_score")
    if isinstance(raw, (int, float)):
        return round(float(raw if raw > 1 else raw * 100), 1)
    return 0.0
