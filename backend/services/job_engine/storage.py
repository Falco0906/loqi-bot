from datetime import datetime, timedelta, timezone
from typing import Optional

from services.job_engine.models import BatchItem, BatchItemStatus, Job, JobStatus
from services.platform.supabase import get_supabase_client


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
                "workspace_id": job.workspace_id or None,
                "campaign_id": job.campaign_id or None,
                "payload": job.payload or {},
                "result": job.result or {},
                "error_message": job.error_message,
                "result_ready": job.result_ready,
                "run_at": job.run_at.isoformat() if job.run_at else None,
                "lease_owner": job.lease_owner or None,
                "lease_expires_at": job.lease_expires_at.isoformat() if job.lease_expires_at else None,
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

    def delete_job(self, job_id: str) -> bool:
        """Remove a job whose dependent batch-item creation did not persist."""
        client = get_supabase_client()
        if not client:
            return False
        try:
            client.table("jobs").delete().eq("id", job_id).execute()
            return True
        except Exception as error:
            _log(f"delete_job error: {error}")
            return False

    def update_job(
        self,
        job_id: str,
        status: Optional[JobStatus] = None,
        stage: Optional[str] = None,
        progress: Optional[int] = None,
        error_message: Optional[str] = None,
        result_ready: Optional[bool] = None,
        result: Optional[dict] = None,
        completed_at: Optional[datetime] = None,
        clear_lease: bool = False,
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
            if result is not None:
                updates["result"] = result
            if completed_at is not None:
                updates["completed_at"] = completed_at.isoformat()
            if clear_lease or status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                updates["lease_owner"] = None
                updates["lease_expires_at"] = None
            client.table("jobs").update(updates).eq("id", job_id).execute()
            return True
        except Exception as e:
            _log(f"update_job error: {e}")
            return False

    def claim_due_jobs(
        self, lease_owner: str, job_types: list[str], *, limit: int = 25, lease_seconds: int = 120,
    ) -> list[Job]:
        """Atomically claim due delayed jobs through the database RPC."""
        if not lease_owner or not job_types:
            return []
        client = get_supabase_client()
        if not client:
            return []
        try:
            result = client.rpc("claim_due_jobs", {
                "p_lease_owner": lease_owner,
                "p_job_types": job_types,
                "p_limit": limit,
                "p_lease_seconds": lease_seconds,
            }).execute()
            return [Job.from_dict(row) for row in (getattr(result, "data", None) or [])]
        except Exception as error:
            _log(f"claim_due_jobs error: {error}")
            return []

    def renew_job_lease(self, job_id: str, lease_owner: str, *, lease_seconds: int = 120) -> bool:
        """Extend one owned running-job lease without reviving another worker's job."""
        client = get_supabase_client()
        if not client or not job_id or not lease_owner:
            return False
        try:
            result = client.table("jobs").update({
                "lease_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", job_id).eq("status", JobStatus.RUNNING.value).eq(
                "lease_owner", lease_owner,
            ).execute()
            return bool(getattr(result, "data", None))
        except Exception as error:
            _log(f"renew_job_lease error: {error}")
            return False

    def cancel_unclaimed_delayed_job(self, job_id: str) -> bool:
        """Cancel a queued delayed job before any worker has claimed it."""
        client = get_supabase_client()
        if not client or not job_id:
            return False
        try:
            result = client.table("jobs").update({
                "status": JobStatus.CANCELLED.value,
                "stage": "Cancelled",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", job_id).eq("status", JobStatus.QUEUED.value).not_.is_(
                "run_at", "null",
            ).execute()
            return bool(getattr(result, "data", None))
        except Exception as error:
            _log(f"cancel_unclaimed_delayed_job error: {error}")
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

    def append_search_results(self, job_id: str, leads: list[dict]) -> bool:
        """PR-4: incremental insert with explicit ranks (first-result path).

        Each lead carries ``_rank``; rows are written immediately so users see
        results before finalize. Dedup at read time by lead identity."""
        client = get_supabase_client()
        if not client:
            return False
        try:
            rows = [
                {
                    "job_id": job_id,
                    "rank": lead.pop("_rank", i + 1),
                    "lead_data": lead,
                }
                for i, lead in enumerate(leads)
            ]
            if rows:
                client.table("search_results").insert(rows).execute()
            return True
        except Exception as e:
            _log(f"append_search_results error: {e}")
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
                client.table("jobs").select("*").eq("user_id", user_id)
                .order("created_at", desc=True).limit(limit).execute()
            )
            return [Job.from_dict(row) for row in (getattr(result, "data", None) or [])]
        except Exception as error:
            _log(f"list_recent_jobs error: {error}")
            return []

    def list_active_jobs_by_type(self, job_type: str) -> list[Job]:
        client = get_supabase_client()
        if not client:
            return []
        try:
            result = client.table("jobs").select("*").eq("type", job_type).in_(
                "status", ["queued", "running"]
            ).order("created_at", desc=False).execute()
            return [Job.from_dict(row) for row in (getattr(result, "data", None) or [])]
        except Exception as error:
            _log(f"list_active_jobs_by_type error: {error}")
            return []

    def create_batch_items(self, items: list[BatchItem]) -> bool:
        """Insert batch items once; the database unique key is the retry guard."""
        client = get_supabase_client()
        if not client:
            return False
        try:
            rows = [{
                "id": item.id, "job_id": item.job_id, "workspace_id": item.workspace_id,
                "campaign_id": item.campaign_id or None, "position": item.position,
                "lead_snapshot": item.lead_snapshot, "idempotency_key": item.idempotency_key,
                "status": item.status.value, "attempt_count": item.attempt_count,
                "last_error": item.last_error, "draft_id": item.draft_id or None,
            } for item in items]
            if rows:
                client.table("job_batch_items").upsert(rows, on_conflict="job_id,idempotency_key").execute()
            return True
        except Exception as error:
            _log(f"create_batch_items error: {error}")
            return False

    def list_batch_resume_items(self, job_id: str, workspace_id: str) -> list[BatchItem]:
        client = get_supabase_client()
        if not client:
            return []
        try:
            result = client.table("job_batch_items").select("*").eq("job_id", job_id).eq(
                "workspace_id", workspace_id
            ).in_("status", ["pending", "generating", "failed"]).order("position").execute()
            return [self._batch_item(row) for row in (getattr(result, "data", None) or [])]
        except Exception as error:
            _log(f"list_batch_resume_items error: {error}")
            return []

    def list_batch_items(self, job_id: str, workspace_id: str) -> list[BatchItem]:
        """Return every persisted item for one workspace-scoped batch job."""
        client = get_supabase_client()
        if not client:
            return []
        try:
            result = client.table("job_batch_items").select("*").eq(
                "job_id", job_id
            ).eq("workspace_id", workspace_id).order("position").execute()
            return [self._batch_item(row) for row in (getattr(result, "data", None) or [])]
        except Exception as error:
            _log(f"list_batch_items error: {error}")
            return []

    def mark_batch_item_completed(self, job_id: str, idempotency_key: str, draft_id: str) -> bool:
        """Complete once. A repeated completion preserves the first draft reference."""
        client = get_supabase_client()
        if not client:
            return False
        try:
            existing = client.table("job_batch_items").select("id,status,draft_id").eq(
                "job_id", job_id
            ).eq("idempotency_key", idempotency_key).limit(1).execute()
            rows = getattr(existing, "data", None) or []
            if not rows:
                return False
            row = rows[0]
            if row.get("status") == BatchItemStatus.COMPLETED.value:
                return str(row.get("draft_id") or "") == draft_id
            client.table("job_batch_items").update({"status": "completed", "draft_id": draft_id, "last_error": "", "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", row["id"]).execute()
            return True
        except Exception as error:
            _log(f"mark_batch_item_completed error: {error}")
            return False

    def mark_batch_item_generating(self, item_id: str) -> bool:
        """Atomically claim a pending item and increment its persisted attempts."""
        client = get_supabase_client()
        if not client:
            return False
        try:
            row = client.table("job_batch_items").select("attempt_count,status").eq("id", item_id).limit(1).execute()
            items = getattr(row, "data", None) or []
            if not items or items[0].get("status") != BatchItemStatus.PENDING.value:
                return False
            result = client.table("job_batch_items").update({
                "status": "generating",
                "attempt_count": int(items[0].get("attempt_count") or 0) + 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", item_id).eq("status", BatchItemStatus.PENDING.value).execute()
            return bool(getattr(result, "data", None))
        except Exception as error:
            _log(f"mark_batch_item_generating error: {error}")
            return False

    def reset_batch_items_for_resume(self, job_id: str, workspace_id: str) -> bool:
        """Make interrupted item claims eligible for one durable restart retry."""
        client = get_supabase_client()
        if not client:
            return False
        try:
            client.table("job_batch_items").update({
                "status": BatchItemStatus.PENDING.value,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("job_id", job_id).eq("workspace_id", workspace_id).in_(
                "status", [BatchItemStatus.GENERATING.value, BatchItemStatus.FAILED.value]
            ).execute()
            return True
        except Exception as error:
            _log(f"reset_batch_items_for_resume error: {error}")
            return False

    def mark_batch_item_failed(self, item_id: str, error: str) -> bool:
        client = get_supabase_client()
        if not client:
            return False
        try:
            client.table("job_batch_items").update({"status": "failed", "last_error": error[:1000], "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", item_id).execute()
            return True
        except Exception as error:
            _log(f"mark_batch_item_failed error: {error}")
            return False
    @staticmethod
    def _batch_item(row: dict) -> BatchItem:
        return BatchItem(
            id=str(row.get("id") or ""), job_id=str(row.get("job_id") or ""), workspace_id=str(row.get("workspace_id") or ""),
            campaign_id=str(row.get("campaign_id") or ""), position=int(row.get("position") or 0),
            lead_snapshot=dict(row.get("lead_snapshot") or {}), idempotency_key=str(row.get("idempotency_key") or ""),
            status=BatchItemStatus(str(row.get("status") or "pending")), attempt_count=int(row.get("attempt_count") or 0),
            last_error=str(row.get("last_error") or ""), draft_id=str(row.get("draft_id") or ""),
        )
