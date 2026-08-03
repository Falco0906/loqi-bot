from __future__ import annotations

from enum import Enum
from typing import AbstractSet, Iterator


class Capability(str, Enum):
    LEAD_SEARCH = "lead_search"
    LEAD_ENRICHMENT = "lead_enrichment"
    COMPANY_ENRICHMENT = "company_enrichment"
    EMAIL_DISCOVERY = "email_discovery"
    EMAIL_VERIFICATION = "email_verification"
    EMAIL_SEND = "email_send"
    EMAIL_RECEIVE = "email_receive"
    EMAIL_SYNC = "email_sync"
    THREAD_SYNC = "thread_sync"
    DRAFT_MANAGE = "draft_manage"
    REPLY_DETECTION = "reply_detection"
    CALENDAR_SYNC = "calendar_sync"
    MEETING_DETECTION = "meeting_detection"
    DRIVE_SYNC = "drive_sync"
    DOCUMENT_DISCOVERY = "document_discovery"
    PROFILE_LOOKUP = "profile_lookup"
    COMPANY_LOOKUP = "company_lookup"
    OAUTH = "oauth"
    LIVE_SEARCH = "live_search"


class CapabilitySet:
    """Immutable set of capabilities with convenience accessors.

    Usage:
        caps = CapabilitySet(Capability.LEAD_SEARCH, Capability.EMAIL_SEND)
        caps.has(Capability.LEAD_SEARCH)  # True
        caps.has_any(Capability.EMAIL_SEND, Capability.EMAIL_RECEIVE)  # True
    """

    def __init__(self, *capabilities: Capability) -> None:
        self._caps = frozenset(capabilities)

    def has(self, capability: Capability) -> bool:
        return capability in self._caps

    def has_any(self, *capabilities: Capability) -> bool:
        return any(c in self._caps for c in capabilities)

    def has_all(self, *capabilities: Capability) -> bool:
        return all(c in self._caps for c in capabilities)

    @property
    def all(self) -> AbstractSet[Capability]:
        return self._caps

    def __iter__(self) -> Iterator[Capability]:
        return iter(self._caps)

    def __len__(self) -> int:
        return len(self._caps)

    def __contains__(self, capability: object) -> bool:
        return capability in self._caps

    def __repr__(self) -> str:
        caps = ", ".join(c.value for c in sorted(self._caps, key=lambda c: c.value))
        return f"CapabilitySet({caps})"

    def to_dict(self) -> dict[str, bool]:
        return {c.value: True for c in self._caps}

    @classmethod
    def from_dict(cls, d: dict[str, bool]) -> CapabilitySet:
        return cls(*(Capability(k) for k, v in d.items() if v))
