from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class CapabilityEventType(str, Enum):
    CAPABILITY_REGISTERED = "capability.registered"
    CAPABILITY_ENABLED = "capability.enabled"
    CAPABILITY_DISABLED = "capability.disabled"
    USAGE_INCREMENTED = "capability.usage.incremented"
    USAGE_RESET = "capability.usage.reset"


@dataclass
class CapabilityDomainEvent:
    event_type: CapabilityEventType
    entity_id: str = ""
    organization_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def capability_registered(
        cls, slug: str, name: str, category: str,
    ) -> CapabilityDomainEvent:
        return cls(
            event_type=CapabilityEventType.CAPABILITY_REGISTERED,
            entity_id=slug,
            data={"name": name, "category": category},
        )

    @classmethod
    def capability_enabled(
        cls, slug: str, organization_id: str, activated_by: str = "",
    ) -> CapabilityDomainEvent:
        return cls(
            event_type=CapabilityEventType.CAPABILITY_ENABLED,
            entity_id=slug,
            organization_id=organization_id,
            data={"activated_by": activated_by},
        )

    @classmethod
    def capability_disabled(
        cls, slug: str, organization_id: str,
    ) -> CapabilityDomainEvent:
        return cls(
            event_type=CapabilityEventType.CAPABILITY_DISABLED,
            entity_id=slug,
            organization_id=organization_id,
        )

    @classmethod
    def usage_incremented(
        cls, slug: str, organization_id: str, field: str, value: int,
    ) -> CapabilityDomainEvent:
        return cls(
            event_type=CapabilityEventType.USAGE_INCREMENTED,
            entity_id=slug,
            organization_id=organization_id,
            data={"field": field, "value": value},
        )
