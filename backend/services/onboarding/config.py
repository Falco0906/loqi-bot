from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OnboardingConfig:
    onboarding_session_ttl_seconds: int = 86400
    max_onboarding_sessions_per_user: int = 5
    max_completed_steps: int = 50


ONBOARDING_CONFIG = OnboardingConfig()
