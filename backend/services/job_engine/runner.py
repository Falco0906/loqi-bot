import asyncio
import os
import socket
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from services.job_engine.models import Job, JobStatus
from services.job_engine.storage import JobStorage
from services.job_engine.registry import get_registry


def _log(msg: str) -> None:
    print(f"[job_runner] {msg}")


class BackgroundRunner:
    def __init__(self, storage: JobStorage):
        self._storage = storage
        self._tasks: dict[str, asyncio.Task] = {}
        self._worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex}"
        self._lease_seconds = 120
        self._lead_tasks: set[str] = set()

    def available_lead_generation_slots(self) -> int:
        return max(0, 2 - len(self._lead_tasks))

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def lease_seconds(self) -> int:
        return self._lease_seconds

    def start_job(
        self,
        job: Job,
        runner_fn=None,
        on_update=None,
        on_complete=None,
        *,
        claimed: bool = False,
    ) -> None:
        if job.run_at is not None and not claimed:
            _log(f"start_job deferred for job={job.id}: delayed jobs require an atomic claim")
            return
        if job.type == "search" and not job.discovery_id:
            _log(f"start_job rejected for job={job.id}: canonical discovery_id is required")
            return
        registration = get_registry().get(job.type)
        runner_fn = runner_fn or (registration.runner_fn if registration else None)
        if runner_fn is None:
            _log(f"start_job rejected for job={job.id}: no workflow registered for type={job.type}")
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        _log(
            f"[kickoff] start_job spawn for job={job.id} discovery_id={job.discovery_id} "
            f"running_loop={'yes' if loop else 'NO RUNNING LOOP'} "
            f"task_count={len(self._tasks)}"
        )
        if loop is None:
            _log(f"[kickoff] start_job ABORTED for job={job.id}: no running event loop")
            return
        task = asyncio.create_task(
            self._run_wrapper(job, runner_fn, on_update, on_complete, claimed=claimed)
        )
        self._tasks[job.id] = task
        if job.type == "lead_strategy":
            self._lead_tasks.add(job.id)
        _log(f"[kickoff] start_job task created for job={job.id}")

    async def _renew_claim_lease(self, job_id: str) -> None:
        """Keep a claimed delayed job reclaimable if this worker dies."""
        while True:
            await asyncio.sleep(max(1, self._lease_seconds // 3))
            renewed = await asyncio.to_thread(
                self._storage.renew_job_lease,
                job_id,
                self._worker_id,
                lease_seconds=self._lease_seconds,
            )
            if not renewed:
                _log(f"lease renewal stopped for job={job_id}: claim is no longer owned")
                return

    async def _run_wrapper(
        self, job: Job, runner_fn, on_update=None, on_complete=None, *, claimed: bool = False,
    ) -> None:
        if job.type == "search" and not job.discovery_id:
            error = "Canonical discovery_id is required"
            _log(f"_run_wrapper rejected job={job.id}: {error}")
            await asyncio.to_thread(
                self._storage.update_job,
                job.id,
                status=JobStatus.FAILED,
                stage="Failed",
                error_message=error,
                completed_at=datetime.now(timezone.utc),
            )
            if on_update:
                on_update({
                    "job_id": job.id,
                    "status": "failed",
                    "stage": "Failed",
                    "progress": 0,
                    "error": error,
                })
            return
        _log(f"[kickoff] _run_wrapper TASK STARTED job={job.id} discovery_id={job.discovery_id}")
        def notify(
            status: str,
            stage: str,
            progress: int,
            error: str = "",
            error_kind: str = "",
        ) -> None:
            if on_update:
                on_update({
                    "job_id": job.id,
                    "status": status,
                    "stage": stage,
                    "progress": progress,
                    "error": error,
                    "error_kind": error_kind,
                })

        async def notify_off_loop(
            status: str,
            stage: str,
            progress: int,
            error: str = "",
            error_kind: str = "",
        ) -> None:
            # PR-P1.2: on_update handlers perform synchronous Supabase writes
            # (discovery progress/status). Run them off the event loop.
            await asyncio.to_thread(notify, status, stage, progress, error, error_kind)

        lease_task = asyncio.create_task(self._renew_claim_lease(job.id)) if claimed else None
        strict_updates = {"strict": True, "lease_owner": self._worker_id} if job.type == "lead_strategy" and claimed else {}
        try:
            if not claimed:
                await asyncio.to_thread(
                    self._storage.update_job,
                    job.id,
                    status=JobStatus.RUNNING,
                    stage="Starting...",
                    progress=0,
                )
            await notify_off_loop("running", "Starting...", 0)

            def on_progress(job_id: str, stage: str, progress: int) -> None:
                # NOTE: executed inside the executor thread that runs the
                # sync pipeline (see run_in_executor in workflow_dispatcher),
                # i.e. already off the event loop.
                self._on_progress(job_id, stage, progress)
                notify("running", stage, progress)

            result = await runner_fn(job, on_progress)
            if result.get("ok"):
                # Discovery finalization is part of successful execution, not
                # a best-effort afterthought. Publish COMPLETED only after
                # the linked Discovery and persisted leads are authoritative.
                if on_complete:
                    try:
                        finalized = await on_complete(job)
                        if finalized is False:
                            error = "Discovery results could not be persisted"
                            await asyncio.to_thread(
                                self._storage.update_job,
                                job.id,
                                status=JobStatus.FAILED,
                                stage="Failed",
                                error_message=error,
                                completed_at=datetime.now(timezone.utc),
                            )
                            await notify_off_loop("failed", "Failed", 0, error, "persistence")
                            return
                    except Exception as e:
                        error = f"Discovery finalization failed: {e}"
                        await asyncio.to_thread(
                            self._storage.update_job,
                            job.id,
                            status=JobStatus.FAILED,
                            stage="Failed",
                            error_message=error,
                            completed_at=datetime.now(timezone.utc),
                        )
                        await notify_off_loop("failed", "Failed", 0, error, "persistence")
                        return
                await asyncio.to_thread(
                    self._storage.update_job,
                    job.id,
                    status=JobStatus.COMPLETED,
                    stage="Complete",
                    progress=100,
                    result_ready=True,
                    result=dict(result.get("result") or {}),
                    completed_at=datetime.now(timezone.utc),
                    **strict_updates,
                )
                await notify_off_loop("completed", "Complete", 100)
            else:
                await asyncio.to_thread(
                    self._storage.update_job,
                    job.id,
                    status=JobStatus.FAILED,
                    stage="Failed",
                    error_message=result.get("error", "Unknown error"),
                    result=dict(result.get("result") or {}),
                    result_ready=bool(result.get("result")),
                    completed_at=datetime.now(timezone.utc),
                    **strict_updates,
                )
                await notify_off_loop(
                    "failed",
                    "Failed",
                    0,
                    result.get("error", "Unknown error"),
                    str(result.get("provider_error_kind") or "execution"),
                )
        except Exception as e:
            if job.type == "lead_strategy":
                # Log identifiers/type, not provider bodies or sensitive input.
                logging.getLogger(__name__).error("lead_generation_worker_failed job_id=%s error_type=%s", job.id, type(e).__name__)
                error_message = "Generation failed; saved partial results remain available."
            else:
                _log(f"job {job.id} crashed: {e}")
                error_message = str(e)
            await asyncio.to_thread(
                self._storage.update_job,
                job.id,
                status=JobStatus.FAILED,
                stage="Failed",
                error_message=error_message,
                completed_at=datetime.now(timezone.utc),
                **strict_updates,
            )
            await notify_off_loop("failed", "Failed", 0, error_message, "execution")
        finally:
            if lease_task:
                lease_task.cancel()
                try:
                    await lease_task
                except asyncio.CancelledError:
                    pass
            self._tasks.pop(job.id, None)
            self._lead_tasks.discard(job.id)

    def _on_progress(self, job_id: str, stage: str, progress: int) -> None:
        self._storage.update_job(
            job_id,
            stage=stage,
            progress=progress,
        )

    def cancel_job(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            self._storage.update_job(
                job_id,
                status=JobStatus.CANCELLED,
                stage="Cancelled",
                completed_at=datetime.now(timezone.utc),
            )
            return True
        return False
