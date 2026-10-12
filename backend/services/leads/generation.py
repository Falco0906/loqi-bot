"""Explicit selected-lead generation, recovered through existing leased jobs.

The jobs row owns both the authorized Phase 4B snapshot and per-lead results.
HTTP disconnection does not cancel work. Restart recovery skips checkpointed
leads; an uncheckpointed model response may need regeneration after a crash.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from services.job_engine import Job, job_manager
from services.job_engine.registry import WorkflowRegistration, get_registry
from services.leads.service import LeadImportError, WorkspaceLeadRepository, analyze_workspace_leads, generate_strategy_from_analysis


def register_lead_generation_workflow() -> None:
    get_registry().register(WorkflowRegistration(
        type="lead_strategy", description="Selected-lead strategy and draft generation",
        runner_fn=run_lead_generation,
    ))


def generation_id(workspace_id: str, actor_id: str, request_key: str) -> str:
    scope = json.dumps([workspace_id, actor_id, request_key], separators=(",", ":"))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "loqi:lead-generation:" + scope))


async def generation_status(workspace_id: str, actor_id: str, job_id: str) -> dict:
    job = await asyncio.to_thread(job_manager._storage.get_job, job_id, strict=True)
    if not job or job.type != "lead_strategy" or job.workspace_id != workspace_id or job.user_id != actor_id:
        raise HTTPException(404, "Generation not found in this workspace")
    return {
        "ok": True, "job_id": job.id, "status": job.status.value,
        "stage": job.stage, "progress": job.progress,
        "error": job.error_message, **job.result,
        "lead_ids": job.payload["lead_ids"],
    }


async def start_lead_generation(workspace_id: str, actor_id: str, lead_ids: list[str], request_key: str) -> dict:
    if not lead_ids or len(lead_ids) > 50 or len(set(lead_ids)) != len(lead_ids):
        raise LeadImportError("Provide between 1 and 50 unique lead IDs")
    identity = generation_id(workspace_id, actor_id, request_key)
    storage = job_manager._storage
    existing = await asyncio.to_thread(storage.get_job, identity, strict=True)
    expected_ids = sorted(lead_ids)
    if existing:
        if existing.payload.get("lead_ids") != expected_ids:
            raise HTTPException(409, "Generation key was already used for different selected leads")
        return await generation_status(workspace_id, actor_id, identity)

    # Validate ownership before creating a durable operation; no model/context
    # calls happen in the request. The worker validates again during hydration.
    slots = asyncio.Semaphore(8)
    repo = WorkspaceLeadRepository()

    async def validate(lead_id):
        async with slots:
            row = await repo.get_for_workspace(lead_id, workspace_id)
        if row is None or getattr(row, "deleted_at", None) is not None:
            raise LeadImportError("One or more selected leads are unavailable in this workspace")

    await asyncio.gather(*(validate(lead_id) for lead_id in lead_ids))
    register_lead_generation_workflow()
    job = Job(id=identity, type="lead_strategy", user_id=actor_id, workspace_id=workspace_id,
              stage="Queued", run_at=datetime.now(timezone.utc), payload={"lead_ids": expected_ids},
              result={"results": []})
    persisted = await asyncio.to_thread(storage.create_job, job, strict=True)
    if persisted is None:
        raise RuntimeError("Generation job creation was not confirmed")
    if persisted.payload.get("lead_ids") != expected_ids:
        raise HTTPException(409, "Generation key was already used for different selected leads")
    # Existing lifespan polling atomically claims due jobs. No request-owned
    # task, fire-and-forget model call, or process-local operation authority.
    return await generation_status(workspace_id, actor_id, identity)


async def run_lead_generation(job: Job, _on_progress) -> dict:
    storage = job_manager._storage
    if not job.lease_owner:
        raise RuntimeError("Selected-lead generation requires a durable worker claim")
    analysis = job.result.get("analysis")
    results = list(job.result.get("results") or [])
    if analysis is not None:
        # Reusing persisted evidence must not reuse stale workspace authority
        # after an interrupted worker or a membership change.
        from services.workspace.access import resolve_workspace_context
        await asyncio.to_thread(resolve_workspace_context, None, job.user_id, job.workspace_id)

    async def checkpoint(current):
        saved = await asyncio.to_thread(
            storage.update_job, job.id, strict=True, lease_owner=job.lease_owner,
            stage="Generating strategy and draft", progress=int(len(current) * 100 / len(job.payload["lead_ids"])),
            result={"analysis": analysis, "results": list(current)}, result_ready=bool(current),
        )
        if not saved:
            raise RuntimeError("Generation checkpoint was not confirmed")

    if analysis is None:
        analysis = await analyze_workspace_leads(job.workspace_id, job.user_id, job.payload["lead_ids"])
        await checkpoint(results)
    generated = await generate_strategy_from_analysis(analysis, existing_results=results, on_result=checkpoint)
    completed = sum(item["status"] == "completed" for item in generated["results"])
    failed = len(generated["results"]) - completed
    return {
        "ok": completed > 0,
        "result": {"analysis": analysis, **generated, "completed": completed, "failed": failed,
                   "outcome": "partial" if completed and failed else "completed" if completed else "failed"},
        "error": "No strategy or draft could be generated." if not completed else "",
    }
