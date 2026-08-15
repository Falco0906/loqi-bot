from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4
from typing import Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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
    error_message: Optional[str] = None
    result_ready: bool = False
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
            "error_message": self.error_message,
            "result_ready": self.result_ready,
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
            error_message=data.get("error_message"),
            result_ready=data.get("result_ready", False),
            created_at=_parse_dt(data.get("created_at")),
            updated_at=_parse_dt(data.get("updated_at")),
            completed_at=_parse_dt(data.get("completed_at")),
        )


def _parse_dt(val) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
