import asyncio
from datetime import datetime, timezone
from typing import Optional

from services.job_engine.models import Job, JobStatus
from services.job_engine.storage import JobStorage


def _log(msg: str) -> None:
    print(f"[job_runner] {msg}")


class BackgroundRunner:
    def __init__(self, storage: JobStorage):
        self._storage = storage
        self._tasks: dict[str, asyncio.Task] = {}

    def start_job(self, job: Job, runner_fn) -> None:
        task = asyncio.create_task(self._run_wrapper(job, runner_fn))
        self._tasks[job.id] = task

    async def _run_wrapper(self, job: Job, runner_fn) -> None:
        try:
            self._storage.update_job(
                job.id,
                status=JobStatus.RUNNING,
                stage="Starting...",
                progress=0,
            )
            result = await runner_fn(job, self._on_progress)
            if result.get("ok"):
                self._storage.update_job(
                    job.id,
                    status=JobStatus.COMPLETED,
                    stage="Complete",
                    progress=100,
                    result_ready=True,
                    completed_at=datetime.now(timezone.utc),
                )
            else:
                self._storage.update_job(
                    job.id,
                    status=JobStatus.FAILED,
                    stage="Failed",
                    error_message=result.get("error", "Unknown error"),
                    completed_at=datetime.now(timezone.utc),
                )
        except Exception as e:
            _log(f"job {job.id} crashed: {e}")
            self._storage.update_job(
                job.id,
                status=JobStatus.FAILED,
                stage="Failed",
                error_message=str(e),
                completed_at=datetime.now(timezone.utc),
            )
        finally:
            self._tasks.pop(job.id, None)

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
