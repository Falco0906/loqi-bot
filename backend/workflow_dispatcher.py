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


def _search_with_progress(
    service: str,
    target: str,
    on_progress: ProgressCallback,
) -> dict:
    def on_stage(stage_idx: int) -> None:
        if stage_idx < len(STAGES_SEARCH):
            pct = int((stage_idx / len(STAGES_SEARCH)) * 100)
            on_progress(STAGES_SEARCH[stage_idx], pct)

    on_stage(0)

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

    result = search_with_expansion(service, target)
    on_stage(3)

    return result


async def run_search_workflow(job: Job, on_progress) -> dict:
    query = job.query.strip()
    if not query:
        return {"ok": False, "error": "Empty query"}

    parts = query.split(" for ", 1)
    if len(parts) == 2:
        service, target = parts[0].strip(), parts[1].strip()
    else:
        parts = query.split(" in ", 1)
        if len(parts) == 2:
            service, target = parts[0].strip(), parts[1].strip()
        else:
            service, target = query, ""

    def progress_callback(stage: str, pct: int) -> None:
        on_progress(job.id, stage, pct)

    result = await asyncio.get_event_loop().run_in_executor(
        None,
        _search_with_progress,
        service,
        target,
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
