from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CapabilityDefinition:
    slug: str = ""
    name: str = ""
    category: str = ""
    description: str = ""
    default_enabled: bool = False
    beta: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OrganizationCapability:
    organization_id: str = ""
    capability_slug: str = ""
    enabled: bool = False
    activated_at: datetime | None = None
    activated_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_active(self) -> bool:
        return self.enabled


@dataclass
class CapabilityUsage:
    organization_id: str = ""
    capability_slug: str = ""
    requests: int = 0
    executions: int = 0
    storage_bytes: int = 0
    api_calls: int = 0
    last_reset: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def reset(self) -> None:
        self.requests = 0
        self.executions = 0
        self.storage_bytes = 0
        self.api_calls = 0
        self.last_reset = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def increment_requests(self, n: int = 1) -> None:
        self.requests += n
        self.updated_at = datetime.now(timezone.utc)

    def increment_executions(self, n: int = 1) -> None:
        self.executions += n
        self.updated_at = datetime.now(timezone.utc)

    def increment_storage(self, bytes_: int) -> None:
        self.storage_bytes += bytes_
        self.updated_at = datetime.now(timezone.utc)

    def increment_api_calls(self, n: int = 1) -> None:
        self.api_calls += n
        self.updated_at = datetime.now(timezone.utc)


@dataclass
class CapabilityLimits:
    organization_id: str = ""
    capability_slug: str = ""
    max_requests: int = 0
    max_executions: int = 0
    max_storage_bytes: int = 0
    max_api_calls: int = 0
    reset_interval_hours: int = 24
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
