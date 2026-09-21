from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4
from typing import Any, Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BatchItemStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobProgress:
    stage: str = ""
    progress: int = 0

    def to_dict(self) -> dict:
        return {"stage": self.stage, "progress": self.progress}


@dataclass
class Job:
    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    type: str = ""
    status: JobStatus = JobStatus.QUEUED
    stage: str = ""
    progress: int = 0
    query: str = ""
    discovery_id: str = ""
    workspace_id: str = ""
    campaign_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    result_ready: bool = False
    run_at: Optional[datetime] = None
    lease_owner: str = ""
    lease_expires_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "user_id": self.user_id,
            "type": self.type,
            "status": self.status.value,
            "stage": self.stage,
            "progress": self.progress,
            "query": self.query,
            "discovery_id": self.discovery_id,
            "workspace_id": self.workspace_id,
            "campaign_id": self.campaign_id,
            "payload": self.payload,
            "result": self.result,
            "error_message": self.error_message,
            "result_ready": self.result_ready,
            "run_at": self.run_at.isoformat() if self.run_at else None,
            "lease_owner": self.lease_owner,
            "lease_expires_at": self.lease_expires_at.isoformat() if self.lease_expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        return cls(
            id=data.get("id", ""),
            user_id=data.get("user_id", ""),
            type=data.get("type", ""),
            status=JobStatus(data.get("status", "queued")),
            stage=data.get("stage", ""),
            progress=data.get("progress", 0),
            query=data.get("query", ""),
            discovery_id=data.get("discovery_id", ""),
            workspace_id=data.get("workspace_id", ""),
            campaign_id=data.get("campaign_id", ""),
            payload=dict(data.get("payload") or {}),
            result=dict(data.get("result") or {}),
            error_message=data.get("error_message"),
            result_ready=data.get("result_ready", False),
            run_at=_parse_dt(data.get("run_at")),
            lease_owner=data.get("lease_owner", "") or "",
            lease_expires_at=_parse_dt(data.get("lease_expires_at")),
            created_at=_parse_dt(data.get("created_at")),
            updated_at=_parse_dt(data.get("updated_at")),
            completed_at=_parse_dt(data.get("completed_at")),
        )


@dataclass
class BatchItem:
    job_id: str
    workspace_id: str
    campaign_id: str
    position: int
    lead_snapshot: dict[str, Any]
    idempotency_key: str
    id: str = field(default_factory=lambda: str(uuid4()))
    status: BatchItemStatus = BatchItemStatus.PENDING
    attempt_count: int = 0
    last_error: str = ""
    draft_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _parse_dt(val) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
