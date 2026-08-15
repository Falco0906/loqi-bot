import asyncio
from typing import Callable, Optional

from services.job_engine.models import Job
from services.job_engine.registry import (
    JobRegistry,
    WorkflowRegistration,
    STAGES_SEARCH,
    get_registry,
)
from services.job_engine.storage import JobStorage
from services.lead_provider import search_with_expansion


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
) -> dict:
    def on_stage(stage_idx: int) -> None:
        if stage_idx < len(STAGES_SEARCH):
            pct = int((stage_idx / len(STAGES_SEARCH)) * 100)
            on_progress(STAGES_SEARCH[stage_idx], pct)

    on_stage(0)

    if plan:
        from services.discovery_plan import icp_from_plan
        icp = icp_from_plan(plan)
        on_stage(1)
    else:
        combined = f"{service} {target}".strip() if target else service

        from services.icp_extractor import extract_structured_icp
        try:
            icp = extract_structured_icp(combined)
            on_stage(1)
        except Exception:
            icp = None

    from services.search_expansion import expand_search_intent
    try:
        expand_search_intent(service, target, icp)
        on_stage(2)
    except Exception:
        pass

    result = search_with_expansion(service, target, plan=plan, context=discovery_context)
    on_stage(3)

    on_stage(4)

    return result


async def run_search_workflow(job: Job, on_progress) -> dict:
    query = job.query.strip()
    if not query:
        return {"ok": False, "error": "Empty query"}

    discovery_context: dict = {}
    try:
        from services.discovery_context import retrieve_discovery_context
        discovery_context = await retrieve_discovery_context(job.user_id, query=query)
    except Exception as e:
        _log(f"workspace context retrieval failed, continuing without it: {e}")

    plan = None
    try:
        from services.discovery_plan import derive_discovery_plan
        plan = derive_discovery_plan(query, existing_context=discovery_context)
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
                from services.discovery import store_discovery_plan
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
    )

    if result.get("ok") and result.get("leads"):
        storage = JobStorage()
        storage.store_search_results(job.id, result["leads"])

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
