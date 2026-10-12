"""Discovery search workflow registration for the durable Job Engine.

This module is not part of the legacy web-workflow state machine under
``services.workflows``. Despite its historical name, it owns the registered
``search`` job-engine runner and belongs with Discovery/Job Engine ownership.
Do not merge it into the legacy workflow runtime during cleanup.
"""

import asyncio
from typing import Callable, Optional

from services.job_engine.models import Job
from services.job_engine.registry import (
    JobRegistry,
    WorkflowRegistration,
    STAGES_SEARCH,
    get_registry,
)
from services.job_engine.storage import JobStorage, SearchResultPersistenceError
from services.discovery.providers import search_with_expansion


def _log(msg: str) -> None:
    print(f"[workflow_dispatcher] {msg}")


ProgressCallback = Callable[[str, int], None]


def _split_query(query: str) -> tuple[str, str]:
    """Legacy free-text split (kept as the fallback when no plan exists)."""
    parts = query.split(" for ", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    parts = query.split(" in ", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return query, ""


def _search_with_progress(
    service: str,
    target: str,
    plan: Optional[dict],
    discovery_context: Optional[dict],
    on_progress: ProgressCallback,
    on_results=None,
) -> dict:
    def on_stage(stage_idx: int) -> None:
        if stage_idx < len(STAGES_SEARCH):
            pct = int((stage_idx / len(STAGES_SEARCH)) * 100)
            on_progress(STAGES_SEARCH[stage_idx], pct)

    on_stage(0)

    if plan:
        from services.discovery.plan import icp_from_plan
        icp = icp_from_plan(plan)
        on_stage(1)
    else:
        combined = f"{service} {target}".strip() if target else service

        from services.discovery.icp import extract_structured_icp
        try:
            icp = extract_structured_icp(combined)
            on_stage(1)
        except Exception:
            icp = None

    # ``search_with_expansion`` owns query expansion. Calling it here as a
    # preflight used to issue the same synchronous LLM request twice before a
    # provider search could begin. Advance the durable progress stage here,
    # then let the provider pipeline perform its single canonical expansion.
    on_stage(2)

    result = search_with_expansion(
        service, target, plan=plan, context=discovery_context,
    )
    on_stage(3)

    # PR-4: first-result hook fires AFTER stage ticks so the "N leads found"
    # progress write isn't immediately overwritten by a later stage label.
    if on_results and result.get("leads"):
        on_results(result["leads"])

    on_stage(4)

    return result


async def run_search_workflow(job: Job, on_progress) -> dict:
    query = job.query.strip()
    if not query:
        return {"ok": False, "error": "Empty query"}

    discovery_context: dict = {}
    workspace_id = job.workspace_id
    if not workspace_id and job.discovery_id:
        # Older durable search jobs omitted this field. Recover the scope
        # from their canonical Discovery, never from the owner's default.
        from services.discovery.service import get_discovery
        discovery = await asyncio.to_thread(get_discovery, job.discovery_id, strict=True)
        workspace_id = str((discovery or {}).get("workspace_id") or "")
        if not workspace_id:
            raise RuntimeError("Discovery workspace could not be loaded")
    try:
        from services.discovery.context import retrieve_discovery_context
        discovery_context = await retrieve_discovery_context(job.user_id, query=query, workspace_id=workspace_id)
    except Exception as e:
        if workspace_id:
            raise
        _log(f"workspace context retrieval failed, continuing without it: {e}")

    plan = None
    try:
        from services.discovery.plan import derive_discovery_plan
        # PR-P1.2: derive_discovery_plan performs a synchronous OpenAI HTTP
        # call (20s timeout via extract_structured_icp). This coroutine runs
        # on the event loop, so offload to a worker thread.
        plan = await asyncio.to_thread(derive_discovery_plan, query, existing_context=discovery_context)
    except Exception as e:
        _log(f"plan derivation failed, using legacy parse: {e}")

    service, target = _split_query(query)
    plan_dict = None
    if plan is not None:
        plan_dict = plan.to_dict()
        if plan_dict.get("offering"):
            service = plan_dict["offering"]
        pl_target = plan_dict.get("target_audience") or ""
        if not pl_target:
            pl_target = ", ".join((plan_dict.get("industries") or [])[:3])
        if pl_target:
            target = pl_target
        if job.discovery_id:
            try:
                from services.discovery.service import store_discovery_plan
                context_provenance = discovery_context.get("provenance") or {}
                _log(
                    f"discovery context provenance job={job.id} discovery={job.discovery_id} "
                    f"knowledge_items={len(context_provenance.get('knowledge_item_ids') or [])} "
                    f"knowledge_sources={len(context_provenance.get('knowledge_source_ids') or [])} "
                    f"strategic_updates={len(context_provenance.get('strategic_update_ids') or [])}"
                )
                stored = await asyncio.to_thread(
                    store_discovery_plan,
                    job.discovery_id,
                    plan_dict,
                    context_provenance,
                )
                if not stored:
                    _log(f"discovery metadata persistence failed job={job.id} discovery={job.discovery_id}")
            except Exception as e:
                _log(f"storing plan failed: {e}")

    # ── PR-4: incremental first-result persistence ──
    # The sync pipeline runs in an executor thread; when the provider returns
    # its first batch we IMMEDIATELY persist it and notify the user — long
    # before finalize. Rank offsets keep multi-batch inserts stable.
    rank_offset = {"n": 0}
    leads_found = {"n": 0}
    provider_leads_seen = {"n": 0}
    staging_failures = {"n": 0}
    workflow_loop = asyncio.get_running_loop()

    def persist_partial(leads: list) -> None:
        """Runs INSIDE the executor thread (no event loop) — sync by design."""
        from services.discovery.service import update_discovery_progress
        provider_leads_seen["n"] += len(leads)
        ranked = [{**lead, "_rank": rank_offset["n"] + i + 1} for i, lead in enumerate(leads)]
        try:
            persisted = JobStorage().append_search_results(job.id, ranked)
        except SearchResultPersistenceError as error:
            cause = error.__cause__ or error
            _log(f"staged result write error job={job.id} error_type={type(cause).__name__} code={getattr(cause, 'code', '')}")
            persisted = False
        if not persisted:
            staging_failures["n"] += 1
            _log(f"staged result write failed job={job.id} persisted_count={leads_found['n']}")
            return
        rank_offset["n"] += len(ranked)
        leads_found["n"] += len(ranked)
        if job.discovery_id:
            if not update_discovery_progress(
                job.discovery_id,
                f"{leads_found['n']} leads found",
                min(99, 10 + leads_found["n"]),
            ):
                _log(f"discovery progress update failed job={job.id}")
        # Publish on the workflow's owning loop after the confirmed write.
        from services.events.bus import EventBus
        bus = EventBus()

        async def _publish():
            await bus.publish_user_event(
                job.user_id, "discovery.leads",
                {"discovery_id": job.discovery_id or ""},
                job_id=job.id,
                status="running",
                progress=leads_found["n"],
            )

        asyncio.run_coroutine_threadsafe(_publish(), workflow_loop).result()

    def progress_callback(stage: str, pct: int) -> None:
        on_progress(job.id, stage, pct)

    result = await asyncio.get_event_loop().run_in_executor(
        None,
        _search_with_progress,
        service,
        target,
        plan_dict,
        discovery_context,
        progress_callback,
        persist_partial,
    )

    # The first-result hook already persisted the provider batch. Inserting
    # the same final batch again doubled Copilot's reported lead count and
    # could make result reads disagree with the finalized Discovery.
    if result.get("ok") and result.get("leads") and leads_found["n"] == 0 and not staging_failures["n"]:
        await asyncio.to_thread(persist_partial, result["leads"])

    if staging_failures["n"]:
        # Persist the incomplete-staging diagnosis before finalization. The
        # finalizer still links confirmed rows, but must not declare success.
        job.result = {**(job.result or {}), "search_staging": {
            "failed_batches": staging_failures["n"],
            "persisted_lead_count": leads_found["n"],
            "provider_lead_count": provider_leads_seen["n"],
        }}
        if not await asyncio.to_thread(JobStorage().update_job, job.id, result=job.result):
            raise SearchResultPersistenceError("Search staging failure could not be recorded")

    return result


def register_workflows() -> None:
    registry = get_registry()
    registry.register(
        WorkflowRegistration(
            type="search",
            description="AI-powered lead search with buyer-intent expansion",
            stages=STAGES_SEARCH,
            runner_fn=run_search_workflow,
        )
    )
    _log(f"Registered workflows: {registry.list_types()}")
