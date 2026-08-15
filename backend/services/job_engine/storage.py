from datetime import datetime, timezone
from typing import Optional

from services.job_engine.models import Job, JobStatus
from services.supabase import get_supabase_client


def _log(msg: str) -> None:
    print(f"[job_storage] {msg}")


class JobStorage:
    def create_job(self, job: Job) -> Optional[Job]:
        client = get_supabase_client()
        if not client:
            _log("create_job: no supabase client")
            return None
        try:
            data = {
                "id": job.id,
                "user_id": job.user_id,
                "type": job.type,
                "status": job.status.value,
                "stage": job.stage,
                "progress": job.progress,
                "query": job.query,
                "discovery_id": job.discovery_id if job.discovery_id else None,
                "error_message": job.error_message,
                "result_ready": job.result_ready,
                "created_at": job.created_at.isoformat(),
                "updated_at": job.updated_at.isoformat(),
            }
            client.table("jobs").insert(data).execute()
            _log(f"create_job: {job.id} type={job.type}")
            return job
        except Exception as e:
            _log(f"create_job error: {e}")
            return None

    def get_job(self, job_id: str) -> Optional[Job]:
        client = get_supabase_client()
        if not client:
            return None
        try:
            result = client.table("jobs").select("*").eq("id", job_id).limit(1).execute()
            rows = result.data if hasattr(result, "data") else []
            if not rows:
                return None
            return Job.from_dict(rows[0])
        except Exception as e:
            _log(f"get_job error: {e}")
            return None

    def update_job(
        self,
        job_id: str,
        status: Optional[JobStatus] = None,
        stage: Optional[str] = None,
        progress: Optional[int] = None,
        error_message: Optional[str] = None,
        result_ready: Optional[bool] = None,
        completed_at: Optional[datetime] = None,
    ) -> bool:
        client = get_supabase_client()
        if not client:
            return False
        try:
            updates: dict = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if status is not None:
                updates["status"] = status.value
            if stage is not None:
                updates["stage"] = stage
            if progress is not None:
                updates["progress"] = progress
            if error_message is not None:
                updates["error_message"] = error_message
            if result_ready is not None:
                updates["result_ready"] = result_ready
            if completed_at is not None:
                updates["completed_at"] = completed_at.isoformat()
            client.table("jobs").update(updates).eq("id", job_id).execute()
            return True
        except Exception as e:
            _log(f"update_job error: {e}")
            return False

    def store_search_results(self, job_id: str, leads: list[dict]) -> bool:
        client = get_supabase_client()
        if not client:
            return False
        try:
            rows = [
                {
                    "job_id": job_id,
                    "rank": i + 1,
                    "lead_data": lead,
                }
                for i, lead in enumerate(leads)
            ]
            if rows:
                client.table("search_results").insert(rows).execute()
            return True
        except Exception as e:
            _log(f"store_search_results error: {e}")
            return False

    def get_search_results(self, job_id: str) -> list[dict]:
        client = get_supabase_client()
        if not client:
            return []
        try:
            result = (
                client.table("search_results")
                .select("*")
                .eq("job_id", job_id)
                .order("rank", desc=False)
                .execute()
            )
            rows = result.data if hasattr(result, "data") else []
            return [r["lead_data"] for r in rows]
        except Exception as e:
            _log(f"get_search_results error: {e}")
            return []

    def list_active_jobs(self, user_id: str) -> list[Job]:
        client = get_supabase_client()
        if not client:
            return []
        try:
            result = (
                client.table("jobs")
                .select("*")
                .eq("user_id", user_id)
                .in_("status", ["queued", "running"])
                .order("created_at", desc=True)
                .execute()
            )
            rows = result.data if hasattr(result, "data") else []
            return [Job.from_dict(r) for r in rows]
        except Exception as e:
            _log(f"list_active_jobs error: {e}")
            return []

    def list_recent_jobs(self, user_id: str, limit: int = 20) -> list[Job]:
        """Return recent jobs so completed research remains discoverable."""
        client = get_supabase_client()
        if not client:
            return []
        try:
            result = (
                client.table("jobs")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            rows = result.data if hasattr(result, "data") else []
            return [Job.from_dict(r) for r in rows]
        except Exception as e:
            _log(f"list_recent_jobs error: {e}")
            return []
