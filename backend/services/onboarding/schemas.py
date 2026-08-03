from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


# ─── Validation types ──────────────────────────────────────────────────


class ValidationError(BaseModel):
    field: str
    message: str


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


class WorkspaceCreateRequest(BaseModel):
    workspace_name: str
    slug: str = ""
    session_token: str = ""


class WorkspaceCreateResponse(BaseModel):
    organization_id: str
    organization_name: str
    organization_slug: str


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
    wizard_data: dict | None = None


class OnboardingStepResponse(BaseModel):
    step: str
    completed: bool
    data: dict | None = None
    next_route: str
    onboarding_complete: bool


# ─── Wizard models ─────────────────────────────────────────────────────

class WizardSaveRequest(BaseModel):
    data: dict
    completed: bool = False


class WizardDataResponse(BaseModel):
    data: dict
    onboarding_complete: bool
    validation_errors: list[ValidationError] | None = None


class WizardSaveResponse(BaseModel):
    data: dict
    onboarding_complete: bool
    validation_errors: list[ValidationError] | None = None
