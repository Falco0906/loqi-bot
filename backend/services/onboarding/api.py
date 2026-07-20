from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from services.onboarding.exceptions import (
    InvalidTransitionException,
    OnboardingException,
    OnboardingSessionExpired,
    OnboardingSessionNotFound,
    StepAlreadyCompletedException,
    StepNotAllowedException,
    StepNotFoundException,
)
from services.onboarding.repositories import (
    InMemoryLifecycleRepository,
    InMemoryOnboardingSessionRepository,
)
from services.onboarding.schemas import (
    CompleteStepRequest,
    OnboardingProgressResponse,
    ProfileRequest,
    WorkspaceRequest,
)
from services.onboarding.services import LifecycleService, OnboardingService

router = APIRouter(prefix="/api/v1/onboarding", tags=["Onboarding"])


# ─── Service wiring ────────────────────────────────────────────────────

def _build_onboarding_service() -> OnboardingService:
    lifecycle_repo = InMemoryLifecycleRepository()
    session_repo = InMemoryOnboardingSessionRepository()
    lifecycle_svc = LifecycleService(lifecycle_repo)
    return OnboardingService(lifecycle_svc, session_repo)


_onboarding_service: OnboardingService | None = None


def _get_service() -> OnboardingService:
    global _onboarding_service
    if _onboarding_service is None:
        _onboarding_service = _build_onboarding_service()
    return _onboarding_service


def set_onboarding_service(svc: OnboardingService | None) -> None:
    global _onboarding_service
    _onboarding_service = svc


def reset_onboarding_service() -> None:
    set_onboarding_service(None)


# ─── Error mapping ─────────────────────────────────────────────────────

_ONBOARDING_STATUS: dict[type[OnboardingException], int] = {
    OnboardingSessionNotFound: 404,
    OnboardingSessionExpired: 410,
    StepNotFoundException: 404,
    StepNotAllowedException: 400,
    StepAlreadyCompletedException: 409,
    InvalidTransitionException: 400,
}


def _onboarding_status(exc: OnboardingException) -> int:
    for cls in type(exc).__mro__:
        if cls in _ONBOARDING_STATUS:
            return _ONBOARDING_STATUS[cls]
    return 400


# ─── Endpoints ─────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=OnboardingProgressResponse,
    summary="Get current onboarding state",
    description="Return the user's current lifecycle state, current step, "
    "completed steps, remaining steps, progress percentage, and next route. "
    "Frontend never infers lifecycle state — it always asks the backend.",
    response_description="Current onboarding progress",
)
async def get_onboarding(user_id: str = ""):
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id query parameter required")
    svc = _get_service()
    return await svc.get_progress(user_id)


@router.post(
    "/profile",
    response_model=OnboardingProgressResponse,
    summary="Complete profile setup",
    description="Submit profile information (display name, avatar, locale). "
    "Advances lifecycle state from AUTHENTICATED or PROFILE_SETUP to "
    "WORKSPACE_SETUP. Returns updated onboarding progress.",
    response_description="Updated onboarding progress",
)
async def complete_profile(user_id: str = "", payload: ProfileRequest | None = None):
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id query parameter required")
    svc = _get_service()
    try:
        _data: dict[str, Any] = {}
        if payload is not None:
            _data = payload.model_dump(exclude_none=True)
        dn = _data.pop("display_name", "")
        await svc.complete_profile(
            user_id,
            display_name=dn,
            **_data,
        )
    except OnboardingException as exc:
        raise HTTPException(
            status_code=_onboarding_status(exc),
            detail=exc.message,
        ) from exc
    return await svc.get_progress(user_id)


@router.post(
    "/workspace",
    response_model=OnboardingProgressResponse,
    summary="Complete workspace setup",
    description="Submit workspace information (workspace name, optional slug). "
    "Advances lifecycle state from WORKSPACE_SETUP to PLAN_SELECTION. "
    "Returns updated onboarding progress.",
    response_description="Updated onboarding progress",
)
async def complete_workspace(user_id: str = "", payload: WorkspaceRequest | None = None):
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id query parameter required")
    svc = _get_service()
    try:
        _data: dict[str, Any] = {}
        if payload is not None:
            _data = payload.model_dump(exclude_none=True)
        ws_name = _data.pop("workspace_name", "")
        await svc.complete_workspace(
            user_id,
            workspace_name=ws_name,
            **_data,
        )
    except OnboardingException as exc:
        raise HTTPException(
            status_code=_onboarding_status(exc),
            detail=exc.message,
        ) from exc
    return await svc.get_progress(user_id)


@router.post(
    "/complete-step",
    response_model=OnboardingProgressResponse,
    summary="Complete any onboarding step",
    description="Generic step completion endpoint. Accepts a step_id and "
    "optional data payload. Validates the step is allowed in the current "
    "lifecycle state and advances the state machine accordingly.",
    response_description="Updated onboarding progress",
)
async def complete_step(payload: CompleteStepRequest, user_id: str = ""):
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id query parameter required")
    svc = _get_service()
    try:
        await svc.complete_step(user_id, payload.step_id, payload.data)
    except OnboardingException as exc:
        raise HTTPException(
            status_code=_onboarding_status(exc),
            detail=exc.message,
        ) from exc
    return await svc.get_progress(user_id)
