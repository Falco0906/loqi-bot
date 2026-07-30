from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OnboardingConfig:
    onboarding_session_ttl_seconds: int = 86400
    max_onboarding_sessions_per_user: int = 5
    max_completed_steps: int = 50


ONBOARDING_CONFIG = OnboardingConfig()


# ─── Adaptive wizard step definitions (future branching) ──────────────


@dataclass
class WizardStepDefinition:
    id: str
    label: str
    description: str = ""
    condition: str | None = None
    depends_on: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


WIZARD_STEP_DEFINITIONS: list[WizardStepDefinition] = [
    WizardStepDefinition(
        id="industry",
        label="What industry are you in?",
        description="Select your primary industry",
    ),
    WizardStepDefinition(
        id="role",
        label="What is your role?",
        description="Select your primary role",
        depends_on="industry",
    ),
    WizardStepDefinition(
        id="goals",
        label="What are your goals?",
        description="Select your primary goals",
        depends_on="role",
    ),
    WizardStepDefinition(
        id="summary",
        label="Review your answers",
        description="Confirm your selections",
        depends_on="goals",
    ),
]
