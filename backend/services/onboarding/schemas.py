from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


# ─── Request models ────────────────────────────────────────────────────

class CompleteStepRequest(BaseModel):
    step_id: str
    data: dict | None = None


class ProfileRequest(BaseModel):
    display_name: str
    avatar_url: str = ""
    locale: str = "en"


class WorkspaceRequest(BaseModel):
    workspace_name: str
    slug: str = ""


# ─── Response models ───────────────────────────────────────────────────

class StepInfo(BaseModel):
    step_id: str
    completed: bool
    completed_at: datetime | None = None


class OnboardingProgressResponse(BaseModel):
    lifecycle_state: str
    current_step: str | None
    next_route: str
    progress_percentage: int
    completed_steps: list[str]
    remaining_steps: list[str]
    total_steps: int
    onboarding_complete: bool


class OnboardingStepResponse(BaseModel):
    step: str
    completed: bool
    data: dict | None = None
    next_route: str
    onboarding_complete: bool
