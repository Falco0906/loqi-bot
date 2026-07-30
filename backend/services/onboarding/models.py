from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class LifecycleState(str, Enum):
    VISITOR = "VISITOR"
    AUTHENTICATED = "AUTHENTICATED"
    PROFILE_SETUP = "PROFILE_SETUP"
    WORKSPACE_SETUP = "WORKSPACE_SETUP"
    PLAN_SELECTION = "PLAN_SELECTION"
    CHECKOUT_PENDING = "CHECKOUT_PENDING"
    SUBSCRIPTION_ACTIVE = "SUBSCRIPTION_ACTIVE"
    ONBOARDING_COMPLETE = "ONBOARDING_COMPLETE"
    ACTIVE = "ACTIVE"


# Ordered by progression. Index is used for transition validation.
# M2.8.4: Onboarding Wizard completes before billing steps.
# Billing steps (PLAN_SELECTION, CHECKOUT) are future — not required for activation.
LIFECYCLE_ORDER: list[LifecycleState] = [
    LifecycleState.VISITOR,
    LifecycleState.AUTHENTICATED,
    LifecycleState.PROFILE_SETUP,
    LifecycleState.WORKSPACE_SETUP,
    LifecycleState.ONBOARDING_COMPLETE,
    LifecycleState.ACTIVE,
    LifecycleState.PLAN_SELECTION,
    LifecycleState.CHECKOUT_PENDING,
    LifecycleState.SUBSCRIPTION_ACTIVE,
]


def is_valid_transition(current: LifecycleState, target: LifecycleState) -> bool:
    if current not in LIFECYCLE_ORDER:
        return False
    if target not in LIFECYCLE_ORDER:
        return False
    current_idx = LIFECYCLE_ORDER.index(current)
    target_idx = LIFECYCLE_ORDER.index(target)
    return target_idx == current_idx + 1


class StepId(str, Enum):
    PROFILE_SETUP = "PROFILE_SETUP"
    WORKSPACE_SETUP = "WORKSPACE_SETUP"
    PLAN_SELECTION = "PLAN_SELECTION"
    CHECKOUT = "CHECKOUT"
    ONBOARDING_WIZARD = "ONBOARDING_WIZARD"


STEP_ORDER: list[StepId] = [
    StepId.PROFILE_SETUP,
    StepId.WORKSPACE_SETUP,
    StepId.ONBOARDING_WIZARD,
    StepId.PLAN_SELECTION,
    StepId.CHECKOUT,
]


STEP_TO_LIFECYCLE: dict[StepId, LifecycleState] = {
    StepId.PROFILE_SETUP: LifecycleState.WORKSPACE_SETUP,
    StepId.WORKSPACE_SETUP: LifecycleState.ONBOARDING_COMPLETE,
    StepId.ONBOARDING_WIZARD: LifecycleState.ACTIVE,
    StepId.PLAN_SELECTION: LifecycleState.CHECKOUT_PENDING,
    StepId.CHECKOUT: LifecycleState.SUBSCRIPTION_ACTIVE,
}


LIFECYCLE_TO_STEP: dict[LifecycleState, StepId | None] = {
    LifecycleState.AUTHENTICATED: StepId.PROFILE_SETUP,
    LifecycleState.PROFILE_SETUP: StepId.PROFILE_SETUP,
    LifecycleState.WORKSPACE_SETUP: StepId.WORKSPACE_SETUP,
    LifecycleState.ONBOARDING_COMPLETE: StepId.ONBOARDING_WIZARD,
    LifecycleState.ACTIVE: None,
    LifecycleState.PLAN_SELECTION: StepId.PLAN_SELECTION,
    LifecycleState.CHECKOUT_PENDING: StepId.CHECKOUT,
    LifecycleState.SUBSCRIPTION_ACTIVE: None,
}


@dataclass
class StepRecord:
    step_id: str = ""
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class OnboardingSession:
    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    lifecycle_state: LifecycleState = LifecycleState.AUTHENTICATED
    completed_steps: list[StepRecord] = field(default_factory=list)
    step_data: dict[str, dict[str, Any]] = field(default_factory=dict)
    is_active: bool = True
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(
        second=0, microsecond=0,
    ) + __import__("datetime").timedelta(hours=24))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at

    def is_step_completed(self, step_id: str) -> bool:
        return any(s.step_id == step_id for s in self.completed_steps)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    def deactivate(self) -> None:
        self.is_active = False
        self.touch()


@dataclass
class UserLifecycle:
    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    state: LifecycleState = LifecycleState.AUTHENTICATED
    active_onboarding_session_id: str = ""
    entered_state_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def transition_to(self, new_state: LifecycleState) -> None:
        self.state = new_state
        self.entered_state_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def touch(self) -> None:
        self.last_activity_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
