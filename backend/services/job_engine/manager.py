from typing import Optional

from services.job_engine.models import Job, JobStatus
from services.job_engine.storage import JobStorage
from services.job_engine.runner import BackgroundRunner
from services.job_engine.registry import get_registry


def _log(msg: str) -> None:
    print(f"[job_manager] {msg}")


class JobManager:
    def __init__(self):
        self._storage = JobStorage()
        self._runner = BackgroundRunner(self._storage)

    async def create_search_job(self, user_id: str, query: str, on_update=None) -> Optional[dict]:
        import asyncio
        from services.job_engine.registry import STAGES_SEARCH

        job = Job(
            user_id=user_id,
            type="search",
            query=query,
            stage=STAGES_SEARCH[0],
            progress=0,
        )
        created = await asyncio.to_thread(self._storage.create_job, job)
        if not created:
            return None

        from workflow_dispatcher import run_search_workflow

        self._runner.start_job(job, run_search_workflow, on_update=on_update)
        return {"job_id": job.id, "status": job.status.value}

    def get_job(self, job_id: str) -> Optional[dict]:
        job = self._storage.get_job(job_id)
        if not job:
            return None
        result = job.to_dict()
        if job.status == JobStatus.COMPLETED and job.result_ready:
            result["result_ready"] = True
        return result

    def get_job_results(self, job_id: str) -> Optional[dict]:
        job = self._storage.get_job(job_id)
        if not job:
            return None
        if job.status != JobStatus.COMPLETED:
            return {"ok": False, "error": "Job not completed"}
        leads = self._storage.get_search_results(job_id)
        return {"ok": True, "leads": leads}

    def cancel_job(self, job_id: str) -> bool:
        return self._runner.cancel_job(job_id)

    def list_active_jobs(self, user_id: str) -> list[dict]:
        jobs = self._storage.list_active_jobs(user_id)
        return [j.to_dict() for j in jobs]
