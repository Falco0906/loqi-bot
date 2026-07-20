from __future__ import annotations

from datetime import datetime, timezone

from typing import TYPE_CHECKING

from services.onboarding.config import ONBOARDING_CONFIG
from services.onboarding.events import OnboardingEvent
from services.onboarding.exceptions import (
    InvalidTransitionException,
    LifecycleStateNotFound,
    OnboardingNotActive,
    OnboardingSessionExpired,
    OnboardingSessionNotFound,
    StepAlreadyCompletedException,
    StepNotAllowedException,
    StepNotFoundException,
)
from services.onboarding.models import (
    LIFECYCLE_ORDER,
    LIFECYCLE_TO_STEP,
    STEP_ORDER,
    STEP_TO_LIFECYCLE,
    LifecycleState,
    OnboardingSession,
    StepId,
    StepRecord,
    UserLifecycle,
    is_valid_transition,
)
from services.onboarding.repositories import (
    InMemoryLifecycleRepository,
    InMemoryOnboardingSessionRepository,
    LifecycleRepository,
    OnboardingSessionRepository,
)

if TYPE_CHECKING:
    from services.organizations.services import OrganizationService


# ─── LifecycleService ────────────────────────────────────────────────


class LifecycleService:

    def __init__(
        self,
        lifecycle_repo: LifecycleRepository,
    ) -> None:
        self._lifecycle_repo = lifecycle_repo

    async def get_or_create(self, user_id: str) -> UserLifecycle:
        existing = await self._lifecycle_repo.find_by_user_id(user_id)
        if existing is not None:
            existing.touch()
            await self._lifecycle_repo.save(existing)
            return existing
        lc = UserLifecycle(user_id=user_id)
        await self._lifecycle_repo.save(lc)
        return lc

    async def get_current_state(self, user_id: str) -> LifecycleState:
        lc = await self._lifecycle_repo.find_by_user_id(user_id)
        if lc is None:
            raise LifecycleStateNotFound(user_id)
        return lc.state

    async def transition(
        self, user_id: str, target: LifecycleState,
    ) -> tuple[UserLifecycle, OnboardingEvent]:
        lc = await self._lifecycle_repo.find_by_user_id(user_id)
        if lc is None:
            lc = UserLifecycle(user_id=user_id)

        if not is_valid_transition(lc.state, target):
            raise InvalidTransitionException(lc.state.value, target.value)

        old_state = lc.state
        lc.transition_to(target)
        await self._lifecycle_repo.save(lc)

        event = OnboardingEvent.lifecycle_transitioned(
            user_id, old_state.value, target.value,
        )
        return lc, event

    async def force_transition(
        self, user_id: str, target: LifecycleState,
    ) -> tuple[UserLifecycle, OnboardingEvent]:
        lc = await self._lifecycle_repo.find_by_user_id(user_id)
        if lc is None:
            lc = UserLifecycle(user_id=user_id)

        old_state = lc.state
        lc.transition_to(target)
        await self._lifecycle_repo.save(lc)

        event = OnboardingEvent.lifecycle_transitioned(
            user_id, old_state.value, target.value,
        )
        return lc, event

    async def is_at_or_after(self, user_id: str, state: LifecycleState) -> bool:
        lc = await self._lifecycle_repo.find_by_user_id(user_id)
        if lc is None:
            return False
        current_idx = LIFECYCLE_ORDER.index(lc.state)
        target_idx = LIFECYCLE_ORDER.index(state)
        return current_idx >= target_idx

    async def get_previous_completed_state(self, user_id: str) -> LifecycleState | None:
        lc = await self._lifecycle_repo.find_by_user_id(user_id)
        if lc is None:
            return None
        current_idx = LIFECYCLE_ORDER.index(lc.state)
        if current_idx <= LIFECYCLE_ORDER.index(LifecycleState.AUTHENTICATED):
            return None
        return LIFECYCLE_ORDER[current_idx - 1]

    async def list_all(self) -> list[UserLifecycle]:
        return await self._lifecycle_repo._all()


# ─── OnboardingService ───────────────────────────────────────────────


class OnboardingService:

    def __init__(
        self,
        lifecycle_service: LifecycleService,
        session_repo: OnboardingSessionRepository,
        org_service: OrganizationService | None = None,
    ) -> None:
        self._lifecycle = lifecycle_service
        self._session_repo = session_repo
        self._org_service = org_service

    async def start_or_resume(self, user_id: str) -> tuple[OnboardingSession, list[OnboardingEvent]]:
        events: list[OnboardingEvent] = []

        lc = await self._lifecycle.get_or_create(user_id)

        existing = await self._session_repo.find_active_by_user_id(user_id)
        if existing is not None:
            existing.touch()
            await self._session_repo.save(existing)
            events.append(OnboardingEvent.onboarding_resumed(user_id, existing.id))
            return existing, events

        session = OnboardingSession(
            user_id=user_id,
            lifecycle_state=lc.state,
            expires_at=datetime.now(timezone.utc).replace(
                second=0, microsecond=0,
            ).replace(hour=0, minute=0, second=0, microsecond=0) + __import__("datetime").timedelta(
                seconds=ONBOARDING_CONFIG.onboarding_session_ttl_seconds,
            ),
        )
        await self._session_repo.save(session)
        events.append(OnboardingEvent.onboarding_started(user_id, session.id))
        return session, events

    async def get_current_step(self, user_id: str) -> OnboardingSession:
        session = await self._session_repo.find_active_by_user_id(user_id)
        if session is None:
            session, _ = await self.start_or_resume(user_id)
        return session

    async def complete_step(
        self, user_id: str, step_id: str, data: dict | None = None,
    ) -> tuple[OnboardingSession, list[OnboardingEvent]]:
        events: list[OnboardingEvent] = []

        session = await self._session_repo.find_active_by_user_id(user_id)
        if session is None:
            session, start_events = await self.start_or_resume(user_id)
            events.extend(start_events)

        if session.is_expired:
            raise OnboardingSessionExpired()

        if step_id not in [s.value for s in StepId]:
            raise StepNotFoundException(step_id)

        if session.is_step_completed(step_id):
            raise StepAlreadyCompletedException(step_id)

        step_enum = StepId(step_id)
        step_idx = STEP_ORDER.index(step_enum)
        for i in range(step_idx):
            prev_step = STEP_ORDER[i].value
            if not session.is_step_completed(prev_step):
                raise StepNotAllowedException(step_id)

        target_state = STEP_TO_LIFECYCLE.get(step_enum)
        current_state = session.lifecycle_state

        if target_state is not None and target_state != current_state:
            lc = await self._lifecycle.get_or_create(user_id)
            try:
                current_lc_state = lc.state
                lc_index = LIFECYCLE_ORDER.index(current_lc_state)
                target_index = LIFECYCLE_ORDER.index(target_state)
                for i in range(lc_index + 1, target_index + 1):
                    intermediate = LIFECYCLE_ORDER[i]
                    _, transition_event = await self._lifecycle.transition(
                        user_id, intermediate,
                    )
                    events.append(transition_event)
                session.lifecycle_state = target_state
            except InvalidTransitionException:
                raise StepNotAllowedException(step_id)

        record = StepRecord(
            step_id=step_id,
            data=data or {},
        )
        session.completed_steps.append(record)
        if data:
            session.step_data[step_id] = data
        session.touch()
        await self._session_repo.save(session)

        events.append(OnboardingEvent.step_completed(user_id, step_id, session.lifecycle_state.value))

        if step_id == StepId.PROFILE_SETUP.value:
            events.append(OnboardingEvent.profile_completed(
                user_id, (data or {}).get("display_name", ""),
            ))
        elif step_id == StepId.WORKSPACE_SETUP.value:
            events.append(OnboardingEvent.workspace_completed(
                user_id, (data or {}).get("workspace_name", ""),
            ))

        if self._is_onboarding_complete(session):
            session.deactivate()
            await self._session_repo.save(session)
            events.append(OnboardingEvent.onboarding_completed(user_id, session.id))

        return session, events

    async def complete_profile(
        self, user_id: str, display_name: str, **extra: str,
    ) -> tuple[OnboardingSession, list[OnboardingEvent]]:
        data = {"display_name": display_name, **extra}
        return await self.complete_step(user_id, StepId.PROFILE_SETUP.value, data)

    async def complete_workspace(
        self, user_id: str, workspace_name: str, **extra: str,
    ) -> tuple[OnboardingSession, list[OnboardingEvent]]:
        if self._org_service is not None:
            try:
                await self._org_service.create_organization(
                    name=workspace_name,
                    created_by=user_id,
                    slug=extra.get("slug"),
                    display_name=workspace_name,
                )
            except Exception:
                pass
        data = {"workspace_name": workspace_name, **extra}
        return await self.complete_step(user_id, StepId.WORKSPACE_SETUP.value, data)

    async def get_progress(self, user_id: str) -> dict:
        lc = await self._lifecycle.get_or_create(user_id)
        session = await self._session_repo.find_active_by_user_id(user_id)
        if session is None:
            if lc.state in (LifecycleState.ACTIVE, LifecycleState.ONBOARDING_COMPLETE):
                completed_ids: set[str] = set()
                all_steps = [s.value for s in STEP_ORDER]
                return {
                    "lifecycle_state": lc.state.value,
                    "current_step": None,
                    "next_route": "/dashboard",
                    "progress_percentage": 100,
                    "completed_steps": all_steps,
                    "remaining_steps": [],
                    "total_steps": len(all_steps),
                    "onboarding_complete": True,
                }
            session, _ = await self.start_or_resume(user_id)

        completed_ids = {s.step_id for s in session.completed_steps}
        all_steps = [s.value for s in STEP_ORDER]
        completed = [s for s in all_steps if s in completed_ids]
        remaining = [s for s in all_steps if s not in completed_ids]
        progress_pct = int((len(completed) / len(all_steps)) * 100) if all_steps else 0

        current_step = self._determine_current_step(session)
        next_route = self._step_to_route(current_step)

        return {
            "lifecycle_state": session.lifecycle_state.value,
            "current_step": current_step.value if current_step else None,
            "next_route": next_route,
            "progress_percentage": progress_pct,
            "completed_steps": completed,
            "remaining_steps": remaining,
            "total_steps": len(all_steps),
            "onboarding_complete": self._is_onboarding_complete(session),
        }

    def _determine_current_step(self, session: OnboardingSession) -> StepId | None:
        completed_ids = {s.step_id for s in session.completed_steps}
        candidate = LIFECYCLE_TO_STEP.get(session.lifecycle_state)

        if candidate is not None and candidate.value not in completed_ids:
            return candidate

        for step in STEP_ORDER:
            if step.value not in completed_ids:
                return step

        return None

    def _step_to_route(self, step: StepId | None) -> str:
        if step is None:
            return "/dashboard"
        mapping = {
            StepId.PROFILE_SETUP: "/onboarding/profile",
            StepId.WORKSPACE_SETUP: "/onboarding/workspace",
            StepId.PLAN_SELECTION: "/onboarding/plan",
            StepId.CHECKOUT: "/onboarding/checkout",
            StepId.ONBOARDING_WIZARD: "/onboarding/wizard",
        }
        return mapping.get(step, "/onboarding")

    def _is_onboarding_complete(self, session: OnboardingSession) -> bool:
        all_steps = {s.value for s in STEP_ORDER}
        completed = {s.step_id for s in session.completed_steps}
        return all_steps.issubset(completed)
