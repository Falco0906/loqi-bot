from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from services.identity.api import get_authenticated_user_id

from services.onboarding.exceptions import (
    InvalidTransitionException,
    OnboardingException,
    OnboardingSessionExpired,
    OnboardingSessionNotFound,
    StepAlreadyCompletedException,
    StepNotAllowedException,
    StepNotFoundException,
)
from services.organizations.exceptions import OrganizationNameTaken, OrganizationSlugTaken
from services.onboarding.repositories import (
    InMemoryLifecycleRepository,
    InMemoryOnboardingSessionRepository,
)
from services.onboarding.schemas import (
    CompleteStepRequest,
    OnboardingProgressResponse,
    ProfileRequest,
    WizardDataResponse,
    WizardSaveRequest,
    WizardSaveResponse,
    WorkspaceCreateRequest,
    WorkspaceCreateResponse,
    WorkspaceRequest,
)
from services.onboarding.services import LifecycleService, OnboardingService

router = APIRouter(prefix="/api/v1/onboarding", tags=["Onboarding"])


# ─── Service wiring ────────────────────────────────────────────────────

_lifecycle_repo = InMemoryLifecycleRepository()
_session_repo = InMemoryOnboardingSessionRepository()


def _build_onboarding_service() -> OnboardingService:
    lifecycle_svc = LifecycleService(_lifecycle_repo)
    return OnboardingService(lifecycle_svc, _session_repo)


_onboarding_service: OnboardingService | None = None
_onboarding_completion_handler = None


def _get_service() -> OnboardingService:
    global _onboarding_service
    if _onboarding_service is None:
        _onboarding_service = _build_onboarding_service()
    return _onboarding_service


def set_onboarding_service(svc: OnboardingService | None) -> None:
    global _onboarding_service
    _onboarding_service = svc


def set_onboarding_completion_handler(handler) -> None:
    """Register the application-level workflow dispatcher.

    The onboarding service remains responsible only for lifecycle state; the
    application composition root owns the research workflow and its events.
    """
    global _onboarding_completion_handler
    _onboarding_completion_handler = handler


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


async def _resolve_user_id(request: Request, requested_user_id: str) -> str:
    """Use the session identity in production; reject mismatched identities."""
    if os.getenv("APP_ENV", "development").lower() == "production":
        authenticated_user_id = await get_authenticated_user_id(request)
        if requested_user_id and requested_user_id != authenticated_user_id:
            raise HTTPException(status_code=403, detail="User identity mismatch")
        return authenticated_user_id

    # Development test fixtures historically call these endpoints with only a
    # user_id. Preserve that contract locally, but still validate it whenever
    # a session header is supplied.
    authorization = request.headers.get("authorization", "")
    if authorization:
        authenticated_user_id = await get_authenticated_user_id(request)
        if requested_user_id and requested_user_id != authenticated_user_id:
            raise HTTPException(status_code=403, detail="User identity mismatch")
        return authenticated_user_id
    if not requested_user_id:
        raise HTTPException(status_code=400, detail="user_id query parameter required")
    return requested_user_id


# ─── Endpoints ─────────────────────────────────────────────────────────


@router.get(
    "/context",
    summary="Get AI personalization context",
    description="Return structured AI Context object assembled from saved "
    "personalization data. This is the canonical source for future AI systems "
    "including Discovery, Mission Control, Campaign Generator, Lead Ranking, "
    "and Memory.",
    response_description="Structured AI Context object",
)
async def get_personalization_context(request: Request, user_id: str = ""):
    user_id = await _resolve_user_id(request, user_id)
    svc = _get_service()
    context = await svc.get_personalization_context(user_id)
    return context


@router.get(
    "",
    response_model=OnboardingProgressResponse,
    summary="Get current onboarding state",
    description="Return the user's current lifecycle state, current step, "
    "completed steps, remaining steps, progress percentage, and next route. "
    "Frontend never infers lifecycle state — it always asks the backend.",
    response_description="Current onboarding progress",
)
async def get_onboarding(request: Request, user_id: str = ""):
    user_id = await _resolve_user_id(request, user_id)
    svc = _get_service()
    progress = await svc.get_progress(user_id)
    wizard = await svc.get_wizard_data(user_id)
    progress["wizard_data"] = wizard or None
    return progress


@router.post(
    "/profile",
    response_model=OnboardingProgressResponse,
    summary="Complete profile setup",
    description="Submit profile information (display name, avatar, locale). "
    "Advances lifecycle state from AUTHENTICATED or PROFILE_SETUP to "
    "WORKSPACE_SETUP. Returns updated onboarding progress.",
    response_description="Updated onboarding progress",
)
async def complete_profile(request: Request, user_id: str = "", payload: ProfileRequest | None = None):
    user_id = await _resolve_user_id(request, user_id)
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
async def complete_workspace(request: Request, user_id: str = "", payload: WorkspaceRequest | None = None):
    user_id = await _resolve_user_id(request, user_id)
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
    "/workspace/create",
    response_model=WorkspaceCreateResponse,
    summary="Create workspace and finalize onboarding",
    description="Creates an organization from workspace data and marks "
    "onboarding as complete. This is the last step — after this the user "
    "is redirected to the dashboard.",
    response_description="Created organization details",
)
async def create_workspace(request: Request, user_id: str = "", payload: WorkspaceCreateRequest | None = None):
    user_id = await _resolve_user_id(request, user_id)
    svc = _get_service()
    try:
        _data: dict[str, object] = {}
        if payload is not None:
            _data = payload.model_dump(exclude_none=True)
        result = await svc.create_workspace_and_finalize(user_id, _data)
    except OnboardingException as exc:
        raise HTTPException(
            status_code=_onboarding_status(exc),
            detail=exc.message,
        ) from exc
    except (OrganizationSlugTaken, OrganizationNameTaken) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if _onboarding_completion_handler is not None:
        try:
            wizard_data = await svc.get_wizard_data(user_id)
            await _onboarding_completion_handler(
                user_id,
                wizard_data,
                _data.get("session_token", ""),
            )
        except Exception as exc:
            # Workspace creation is durable; surface the research failure via
            # workflow events and let the user enter Mission Control.
            import logging
            logging.getLogger("loqi.onboarding").exception("Initial research dispatch failed: %s", exc)
    return result


@router.post(
    "/complete-step",
    response_model=OnboardingProgressResponse,
    summary="Complete any onboarding step",
    description="Generic step completion endpoint. Accepts a step_id and "
    "optional data payload. Validates the step is allowed in the current "
    "lifecycle state and advances the state machine accordingly.",
    response_description="Updated onboarding progress",
)
async def complete_step(request: Request, payload: CompleteStepRequest, user_id: str = ""):
    user_id = await _resolve_user_id(request, user_id)
    svc = _get_service()
    try:
        await svc.complete_step(user_id, payload.step_id, payload.data)
    except OnboardingException as exc:
        raise HTTPException(
            status_code=_onboarding_status(exc),
            detail=exc.message,
        ) from exc
    return await svc.get_progress(user_id)


@router.get(
    "/wizard",
    response_model=WizardDataResponse,
    summary="Get onboarding wizard data",
    description="Return the user's saved onboarding wizard data. Used to "
    "resume the wizard after refresh or browser close.",
    response_description="Saved wizard data and completion status",
)
async def get_wizard(request: Request, user_id: str = ""):
    user_id = await _resolve_user_id(request, user_id)
    svc = _get_service()
    data = await svc.get_wizard_data(user_id)
    progress = await svc.get_progress(user_id)
    validation_errors = await svc.validate_wizard_data(data)
    return WizardDataResponse(
        data=data,
        onboarding_complete=progress.get("onboarding_complete", False),
        validation_errors=validation_errors or None,
    )


@router.post(
    "/wizard",
    response_model=WizardSaveResponse,
    summary="Save onboarding wizard data",
    description="Save onboarding wizard responses. Each call persists "
    "immediately. If completed=True, the wizard step is marked done and "
    "lifecycle advances. Returns saved data and completion status.",
    response_description="Saved wizard data and completion status",
)
async def save_wizard(request: Request, payload: WizardSaveRequest, user_id: str = ""):
    user_id = await _resolve_user_id(request, user_id)
    svc = _get_service()
    validation_errors = await svc.validate_wizard_data(payload.data)
    if payload.completed and validation_errors:
        return WizardSaveResponse(
            data=payload.data,
            onboarding_complete=False,
            validation_errors=validation_errors,
        )
    try:
        if payload.completed:
            _, events = await svc.complete_wizard(user_id, payload.data)
        else:
            await svc.save_wizard_data(user_id, payload.data)
    except OnboardingException as exc:
        raise HTTPException(
            status_code=_onboarding_status(exc),
            detail=exc.message,
        ) from exc
    progress = await svc.get_progress(user_id)
    saved = await svc.get_wizard_data(user_id)
    return WizardSaveResponse(
        data=saved,
        onboarding_complete=progress.get("onboarding_complete", False),
        validation_errors=validation_errors or None,
    )
