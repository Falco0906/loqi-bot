from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class OnboardingEventType(str, Enum):
    ONBOARDING_STARTED = "onboarding.started"
    ONBOARDING_RESUMED = "onboarding.resumed"
    ONBOARDING_COMPLETED = "onboarding.completed"
    ONBOARDING_ABANDONED = "onboarding.abandoned"
    LIFECYCLE_TRANSITIONED = "lifecycle.transitioned"
    STEP_COMPLETED = "step.completed"
    PROFILE_COMPLETED = "profile.completed"
    WORKSPACE_COMPLETED = "workspace.completed"


@dataclass
class OnboardingEvent:
    event_type: OnboardingEventType
    entity_id: str = ""
    actor_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def onboarding_started(cls, user_id: str, session_id: str) -> OnboardingEvent:
        return cls(
            event_type=OnboardingEventType.ONBOARDING_STARTED,
            entity_id=session_id,
            actor_id=user_id,
            data={"user_id": user_id},
        )

    @classmethod
    def onboarding_resumed(cls, user_id: str, session_id: str) -> OnboardingEvent:
        return cls(
            event_type=OnboardingEventType.ONBOARDING_RESUMED,
            entity_id=session_id,
            actor_id=user_id,
        )

    @classmethod
    def onboarding_completed(cls, user_id: str, session_id: str) -> OnboardingEvent:
        return cls(
            event_type=OnboardingEventType.ONBOARDING_COMPLETED,
            entity_id=session_id,
            actor_id=user_id,
            data={"user_id": user_id},
        )

    @classmethod
    def lifecycle_transitioned(cls, user_id: str, from_state: str, to_state: str) -> OnboardingEvent:
        return cls(
            event_type=OnboardingEventType.LIFECYCLE_TRANSITIONED,
            entity_id=user_id,
            actor_id=user_id,
            data={"from_state": from_state, "to_state": to_state},
        )

    @classmethod
    def step_completed(cls, user_id: str, step_id: str, state_at_completion: str) -> OnboardingEvent:
        return cls(
            event_type=OnboardingEventType.STEP_COMPLETED,
            entity_id=user_id,
            actor_id=user_id,
            data={"step_id": step_id, "state": state_at_completion},
        )

    @classmethod
    def profile_completed(cls, user_id: str, display_name: str) -> OnboardingEvent:
        return cls(
            event_type=OnboardingEventType.PROFILE_COMPLETED,
            entity_id=user_id,
            actor_id=user_id,
            data={"display_name": display_name},
        )

    @classmethod
    def workspace_completed(cls, user_id: str, workspace_name: str) -> OnboardingEvent:
        return cls(
            event_type=OnboardingEventType.WORKSPACE_COMPLETED,
            entity_id=user_id,
            actor_id=user_id,
            data={"workspace_name": workspace_name},
        )
