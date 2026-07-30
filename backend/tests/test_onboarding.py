"""Tests for M1.4 — User Onboarding Foundation.

Tests the complete onboarding lifecycle: state machine transitions,
step completion, resume support, progress calculation, validation,
and API endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from services.onboarding.api import (
    reset_onboarding_service,
    set_onboarding_service,
)
from services.onboarding.exceptions import (
    InvalidTransitionException,
    OnboardingSessionExpired,
    OnboardingSessionNotFound,
    StepAlreadyCompletedException,
    StepNotAllowedException,
    StepNotFoundException,
)
from services.onboarding.models import (
    LIFECYCLE_ORDER,
    STEP_ORDER,
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
)
from services.onboarding.services import LifecycleService, OnboardingService


# ─── Helpers ──────────────────────────────────────────────────────────

def _fresh_services() -> tuple[LifecycleService, OnboardingService]:
    lifecycle_repo = InMemoryLifecycleRepository()
    session_repo = InMemoryOnboardingSessionRepository()
    lifecycle_svc = LifecycleService(lifecycle_repo)
    onboarding_svc = OnboardingService(lifecycle_svc, session_repo)
    return lifecycle_svc, onboarding_svc


def _fresh_api_service() -> OnboardingService:
    _, svc = _fresh_services()
    set_onboarding_service(svc)
    return svc


@pytest.fixture(autouse=True)
def _reset():
    reset_onboarding_service()


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════════
# 1. LifecycleState — Model and validation
# ═══════════════════════════════════════════════════════════════════════

class TestLifecycleStateMachine:

    def test_lifecycle_order_has_all_states(self):
        assert len(LIFECYCLE_ORDER) == 9
        assert LIFECYCLE_ORDER[0] == LifecycleState.VISITOR
        assert LIFECYCLE_ORDER[-1] == LifecycleState.SUBSCRIPTION_ACTIVE

    def test_valid_transitions(self):
        assert is_valid_transition(LifecycleState.VISITOR, LifecycleState.AUTHENTICATED)
        assert is_valid_transition(LifecycleState.AUTHENTICATED, LifecycleState.PROFILE_SETUP)
        assert is_valid_transition(LifecycleState.PROFILE_SETUP, LifecycleState.WORKSPACE_SETUP)
        assert is_valid_transition(LifecycleState.WORKSPACE_SETUP, LifecycleState.ONBOARDING_COMPLETE)
        assert is_valid_transition(LifecycleState.ONBOARDING_COMPLETE, LifecycleState.ACTIVE)
        assert is_valid_transition(LifecycleState.ACTIVE, LifecycleState.PLAN_SELECTION)
        assert is_valid_transition(LifecycleState.PLAN_SELECTION, LifecycleState.CHECKOUT_PENDING)
        assert is_valid_transition(LifecycleState.CHECKOUT_PENDING, LifecycleState.SUBSCRIPTION_ACTIVE)

    def test_invalid_transition_skip_state(self):
        assert not is_valid_transition(LifecycleState.VISITOR, LifecycleState.PROFILE_SETUP)
        assert not is_valid_transition(LifecycleState.AUTHENTICATED, LifecycleState.WORKSPACE_SETUP)
        assert not is_valid_transition(LifecycleState.PROFILE_SETUP, LifecycleState.ONBOARDING_COMPLETE)

    def test_invalid_transition_reverse(self):
        assert not is_valid_transition(LifecycleState.ACTIVE, LifecycleState.AUTHENTICATED)
        assert not is_valid_transition(LifecycleState.ONBOARDING_COMPLETE, LifecycleState.PROFILE_SETUP)

    def test_invalid_transition_same_state(self):
        assert not is_valid_transition(LifecycleState.AUTHENTICATED, LifecycleState.AUTHENTICATED)
        assert not is_valid_transition(LifecycleState.ACTIVE, LifecycleState.ACTIVE)

    def test_unknown_state(self):
        assert not is_valid_transition("BOGUS", LifecycleState.AUTHENTICATED)


# ═══════════════════════════════════════════════════════════════════════
# 2. LifecycleService
# ═══════════════════════════════════════════════════════════════════════

class TestLifecycleService:

    @pytest.mark.asyncio
    async def test_get_or_create_creates_new(self):
        lc, _ = _fresh_services()
        result = await lc.get_or_create("user_1")
        assert result.user_id == "user_1"
        assert result.state == LifecycleState.AUTHENTICATED

    @pytest.mark.asyncio
    async def test_get_or_create_returns_existing(self):
        lc, _ = _fresh_services()
        result1 = await lc.get_or_create("user_1")
        result2 = await lc.get_or_create("user_1")
        assert result1.id == result2.id

    @pytest.mark.asyncio
    async def test_get_current_state(self):
        lc, _ = _fresh_services()
        await lc.get_or_create("user_1")
        state = await lc.get_current_state("user_1")
        assert state == LifecycleState.AUTHENTICATED

    @pytest.mark.asyncio
    async def test_get_current_state_not_found(self):
        lc, _ = _fresh_services()
        with pytest.raises(Exception):
            await lc.get_current_state("nonexistent")

    @pytest.mark.asyncio
    async def test_transition_forward(self):
        lc, _ = _fresh_services()
        await lc.get_or_create("user_1")
        result, event = await lc.transition("user_1", LifecycleState.PROFILE_SETUP)
        assert result.state == LifecycleState.PROFILE_SETUP
        assert event.event_type.value == "lifecycle.transitioned"
        assert event.data["from_state"] == "AUTHENTICATED"
        assert event.data["to_state"] == "PROFILE_SETUP"

    @pytest.mark.asyncio
    async def test_transition_invalid_raises(self):
        lc, _ = _fresh_services()
        await lc.get_or_create("user_1")
        with pytest.raises(InvalidTransitionException) as exc:
            await lc.transition("user_1", LifecycleState.ACTIVE)
        assert "AUTHENTICATED" in str(exc.value)
        assert "ACTIVE" in str(exc.value)

    @pytest.mark.asyncio
    async def test_force_transition_skips_validation(self):
        lc, _ = _fresh_services()
        await lc.get_or_create("user_1")
        result, _ = await lc.force_transition("user_1", LifecycleState.ACTIVE)
        assert result.state == LifecycleState.ACTIVE

    @pytest.mark.asyncio
    async def test_is_at_or_after(self):
        lc, _ = _fresh_services()
        await lc.get_or_create("user_1")
        await lc.transition("user_1", LifecycleState.PROFILE_SETUP)
        assert await lc.is_at_or_after("user_1", LifecycleState.AUTHENTICATED) is True
        assert await lc.is_at_or_after("user_1", LifecycleState.PROFILE_SETUP) is True
        assert await lc.is_at_or_after("user_1", LifecycleState.WORKSPACE_SETUP) is False

    @pytest.mark.asyncio
    async def test_is_at_or_after_no_lifecycle(self):
        lc, _ = _fresh_services()
        assert await lc.is_at_or_after("nonexistent", LifecycleState.AUTHENTICATED) is False

    @pytest.mark.asyncio
    async def test_full_lifecycle_transitions(self):
        lc, _ = _fresh_services()
        await lc.get_or_create("user_full")
        transitions = [
            LifecycleState.PROFILE_SETUP,
            LifecycleState.WORKSPACE_SETUP,
            LifecycleState.ONBOARDING_COMPLETE,
            LifecycleState.ACTIVE,
            LifecycleState.PLAN_SELECTION,
            LifecycleState.CHECKOUT_PENDING,
            LifecycleState.SUBSCRIPTION_ACTIVE,
        ]
        for target in transitions:
            result, _ = await lc.transition("user_full", target)
            assert result.state == target


# ═══════════════════════════════════════════════════════════════════════
# 3. OnboardingService — Step completion
# ═══════════════════════════════════════════════════════════════════════

class TestOnboardingStepCompletion:

    @pytest.mark.asyncio
    async def test_start_or_resume_creates_session(self):
        lc, svc = _fresh_services()
        await lc.get_or_create("user_1")
        session, events = await svc.start_or_resume("user_1")
        assert session.user_id == "user_1"
        assert session.is_active is True
        assert len(events) == 1
        assert events[0].event_type.value == "onboarding.started"

    @pytest.mark.asyncio
    async def test_start_or_resume_returns_existing(self):
        lc, svc = _fresh_services()
        await lc.get_or_create("user_1")
        session1, _ = await svc.start_or_resume("user_1")
        session2, events = await svc.start_or_resume("user_1")
        assert session1.id == session2.id
        assert len(events) == 1
        assert events[0].event_type.value == "onboarding.resumed"

    @pytest.mark.asyncio
    async def test_complete_profile_step(self):
        lc, svc = _fresh_services()
        await lc.get_or_create("user_1")
        session, events = await svc.complete_profile("user_1", display_name="Alice")
        assert session.is_step_completed(StepId.PROFILE_SETUP.value)
        assert session.lifecycle_state == LifecycleState.WORKSPACE_SETUP

        event_types = [e.event_type.value for e in events]
        assert "step.completed" in event_types
        assert "profile.completed" in event_types
        assert "lifecycle.transitioned" in event_types

    @pytest.mark.asyncio
    async def test_complete_workspace_step(self):
        lc, svc = _fresh_services()
        await lc.get_or_create("user_1")
        await svc.complete_profile("user_1", display_name="Alice")
        session, events = await svc.complete_workspace("user_1", workspace_name="Alice Corp")
        assert session.is_step_completed(StepId.WORKSPACE_SETUP.value)
        assert session.lifecycle_state == LifecycleState.ONBOARDING_COMPLETE

        event_types = [e.event_type.value for e in events]
        assert "workspace.completed" in event_types

    @pytest.mark.asyncio
    async def test_complete_step_generic(self):
        lc, svc = _fresh_services()
        await lc.get_or_create("user_1")
        session, events = await svc.complete_step(
            "user_1", StepId.PROFILE_SETUP.value, {"display_name": "Bob"},
        )
        assert session.is_step_completed(StepId.PROFILE_SETUP.value)
        assert session.lifecycle_state == LifecycleState.WORKSPACE_SETUP

    @pytest.mark.asyncio
    async def test_step_not_found(self):
        _, onboarding = _fresh_services()
        with pytest.raises(StepNotFoundException):
            await onboarding.complete_step("user_1", "BOGUS_STEP", {})

    @pytest.mark.asyncio
    async def test_step_already_completed_raises(self):
        lc, svc = _fresh_services()
        await lc.get_or_create("user_1")
        await svc.complete_profile("user_1", display_name="Alice")
        with pytest.raises(StepAlreadyCompletedException):
            await svc.complete_profile("user_1", display_name="Alice Again")

    @pytest.mark.asyncio
    async def test_step_out_of_order_raises(self):
        lc, svc = _fresh_services()
        await lc.get_or_create("user_1")
        with pytest.raises(StepNotAllowedException):
            await svc.complete_workspace("user_1", workspace_name="No Profile Yet")

    @pytest.mark.asyncio
    async def test_complete_no_active_session_auto_starts(self):
        _, onboarding = _fresh_services()
        session, events = await onboarding.complete_step(
            "user_1", StepId.PROFILE_SETUP.value, {"display_name": "Auto"},
        )
        assert session.is_step_completed(StepId.PROFILE_SETUP.value)
        assert any(e.event_type.value == "onboarding.started" for e in events)

    @pytest.mark.asyncio
    async def test_step_data_preserved(self):
        lc, svc = _fresh_services()
        await lc.get_or_create("user_1")
        data = {"display_name": "Charlie", "avatar_url": "https://example.com/avatar.png"}
        session, _ = await svc.complete_profile("user_1", **data)
        assert session.step_data[StepId.PROFILE_SETUP.value] == data

    @pytest.mark.asyncio
    async def test_complete_all_steps(self):
        lc, svc = _fresh_services()
        await lc.get_or_create("user_full")
        await svc.start_or_resume("user_full")
        await svc.complete_profile("user_full", display_name="Diana")
        await svc.complete_workspace("user_full", workspace_name="D Corp")
        await svc.complete_step("user_full", StepId.ONBOARDING_WIZARD.value, {})
        await svc.complete_step("user_full", StepId.PLAN_SELECTION.value, {"plan": "free"})
        session, events = await svc.complete_step(
            "user_full", StepId.CHECKOUT.value, {"checkout": "done"},
        )
        assert session.is_active is False
        event_types = [e.event_type.value for e in events]
        assert "onboarding.completed" in event_types


# ═══════════════════════════════════════════════════════════════════════
# 4. OnboardingService — Progress
# ═══════════════════════════════════════════════════════════════════════

class TestOnboardingProgress:

    @pytest.mark.asyncio
    async def test_progress_at_start(self):
        lc, svc = _fresh_services()
        await lc.get_or_create("user_1")
        progress = await svc.get_progress("user_1")
        assert progress["lifecycle_state"] == "AUTHENTICATED"
        assert progress["current_step"] == "PROFILE_SETUP"
        assert progress["next_route"] == "/onboarding/profile"
        assert progress["progress_percentage"] == 0
        assert progress["completed_steps"] == []
        assert progress["onboarding_complete"] is False

    @pytest.mark.asyncio
    async def test_progress_after_profile(self):
        lc, svc = _fresh_services()
        await lc.get_or_create("user_1")
        await svc.complete_profile("user_1", display_name="Alice")
        progress = await svc.get_progress("user_1")
        assert progress["lifecycle_state"] == "WORKSPACE_SETUP"
        assert progress["current_step"] == "WORKSPACE_SETUP"
        assert progress["progress_percentage"] == 20
        assert progress["completed_steps"] == ["PROFILE_SETUP"]

    @pytest.mark.asyncio
    async def test_progress_after_workspace(self):
        lc, svc = _fresh_services()
        await lc.get_or_create("user_1")
        await svc.complete_profile("user_1", display_name="Alice")
        await svc.complete_workspace("user_1", workspace_name="Alice Corp")
        progress = await svc.get_progress("user_1")
        assert progress["lifecycle_state"] == "ONBOARDING_COMPLETE"
        assert progress["current_step"] == "ONBOARDING_WIZARD"
        assert progress["progress_percentage"] == 40
        assert len(progress["completed_steps"]) == 2

    @pytest.mark.asyncio
    async def test_progress_complete(self):
        lc, svc = _fresh_services()
        await lc.get_or_create("user_full")
        await svc.start_or_resume("user_full")
        await svc.complete_profile("user_full", display_name="Diana")
        await svc.complete_workspace("user_full", workspace_name="D Corp")
        await svc.complete_step("user_full", StepId.ONBOARDING_WIZARD.value, {})
        await svc.complete_step("user_full", StepId.PLAN_SELECTION.value, {"plan": "free"})
        await svc.complete_step("user_full", StepId.CHECKOUT.value, {"checkout": "done"})
        progress = await svc.get_progress("user_full")
        assert progress["lifecycle_state"] == "SUBSCRIPTION_ACTIVE"
        assert progress["current_step"] is None
        assert progress["next_route"] == "/dashboard"
        assert progress["progress_percentage"] == 100
        assert progress["onboarding_complete"] is True

    @pytest.mark.asyncio
    async def test_progress_after_resume(self):
        lifecycle_repo = InMemoryLifecycleRepository()
        session_repo = InMemoryOnboardingSessionRepository()
        lifecycle_svc = LifecycleService(lifecycle_repo)

        onboarding1 = OnboardingService(lifecycle_svc, session_repo)
        await lifecycle_svc.get_or_create("user_1")
        await onboarding1.complete_profile("user_1", display_name="Alice")

        onboarding2 = OnboardingService(lifecycle_svc, session_repo)
        progress = await onboarding2.get_progress("user_1")
        assert progress["lifecycle_state"] == "WORKSPACE_SETUP"
        assert progress["current_step"] == "WORKSPACE_SETUP"


# ═══════════════════════════════════════════════════════════════════════
# 5. API endpoints
# ═══════════════════════════════════════════════════════════════════════

class TestOnboardingAPI:

    def test_get_onboarding_requires_user_id(self, client):
        resp = client.get("/api/v1/onboarding")
        assert resp.status_code == 400

    def test_get_onboarding_returns_progress(self, client):
        _fresh_api_service()
        resp = client.get("/api/v1/onboarding", params={"user_id": "user_api_1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["lifecycle_state"] == "AUTHENTICATED"
        assert data["current_step"] == "PROFILE_SETUP"
        assert data["next_route"] == "/onboarding/profile"
        assert data["progress_percentage"] == 0
        assert data["completed_steps"] == []
        assert data["onboarding_complete"] is False

    def test_complete_profile(self, client):
        _fresh_api_service()
        resp = client.post(
            "/api/v1/onboarding/profile",
            params={"user_id": "user_api_2"},
            json={"display_name": "Alice", "locale": "en"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["lifecycle_state"] == "WORKSPACE_SETUP"
        assert data["current_step"] == "WORKSPACE_SETUP"
        assert data["completed_steps"] == ["PROFILE_SETUP"]

    def test_complete_profile_then_workspace(self, client):
        _fresh_api_service()
        client.post(
            "/api/v1/onboarding/profile",
            params={"user_id": "user_api_3"},
            json={"display_name": "Bob"},
        )
        resp = client.post(
            "/api/v1/onboarding/workspace",
            params={"user_id": "user_api_3"},
            json={"workspace_name": "Bob Corp"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["lifecycle_state"] == "ONBOARDING_COMPLETE"
        assert data["completed_steps"] == ["PROFILE_SETUP", "WORKSPACE_SETUP"]

    def test_complete_step_generic(self, client):
        _fresh_api_service()
        resp = client.post(
            "/api/v1/onboarding/complete-step",
            params={"user_id": "user_api_4"},
            json={"step_id": "PROFILE_SETUP", "data": {"display_name": "Carol"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["lifecycle_state"] == "WORKSPACE_SETUP"
        assert data["completed_steps"] == ["PROFILE_SETUP"]

    def test_complete_step_not_found(self, client):
        _fresh_api_service()
        resp = client.post(
            "/api/v1/onboarding/complete-step",
            params={"user_id": "user_api_5"},
            json={"step_id": "BOGUS_STEP"},
        )
        assert resp.status_code == 404

    def test_complete_profile_without_user_id(self, client):
        _fresh_api_service()
        resp = client.post(
            "/api/v1/onboarding/profile",
            json={"display_name": "NoUser"},
        )
        assert resp.status_code == 400

    def test_complete_workspace_without_user_id(self, client):
        _fresh_api_service()
        resp = client.post(
            "/api/v1/onboarding/workspace",
            json={"workspace_name": "NoWorkspace"},
        )
        assert resp.status_code == 400

    def test_complete_step_out_of_order(self, client):
        _fresh_api_service()
        resp = client.post(
            "/api/v1/onboarding/complete-step",
            params={"user_id": "user_api_6"},
            json={"step_id": "WORKSPACE_SETUP", "data": {"workspace_name": "Skip Profile"}},
        )
        assert resp.status_code == 400

    def test_complete_step_already_completed(self, client):
        _fresh_api_service()
        client.post(
            "/api/v1/onboarding/profile",
            params={"user_id": "user_api_7"},
            json={"display_name": "Dup"},
        )
        resp = client.post(
            "/api/v1/onboarding/profile",
            params={"user_id": "user_api_7"},
            json={"display_name": "Dup Again"},
        )
        assert resp.status_code == 409

    def test_full_onboarding_api_lifecycle(self, client):
        _fresh_api_service()
        uid = "user_full_api"

        # Step 1: Profile
        resp = client.post(
            "/api/v1/onboarding/profile",
            params={"user_id": uid},
            json={"display_name": "Full", "locale": "en"},
        )
        assert resp.status_code == 200
        assert resp.json()["lifecycle_state"] == "WORKSPACE_SETUP"

        # Step 2: Workspace
        resp = client.post(
            "/api/v1/onboarding/workspace",
            params={"user_id": uid},
            json={"workspace_name": "Full Corp"},
        )
        assert resp.status_code == 200
        assert resp.json()["lifecycle_state"] == "ONBOARDING_COMPLETE"

        # Step 3: Onboarding wizard
        resp = client.post(
            "/api/v1/onboarding/complete-step",
            params={"user_id": uid},
            json={"step_id": "ONBOARDING_WIZARD", "data": {}},
        )
        assert resp.status_code == 200
        assert resp.json()["lifecycle_state"] == "ACTIVE"

        # Step 4: Plan selection
        resp = client.post(
            "/api/v1/onboarding/complete-step",
            params={"user_id": uid},
            json={"step_id": "PLAN_SELECTION", "data": {"plan": "free"}},
        )
        assert resp.status_code == 200
        assert resp.json()["lifecycle_state"] == "CHECKOUT_PENDING"

        # Step 5: Checkout
        resp = client.post(
            "/api/v1/onboarding/complete-step",
            params={"user_id": uid},
            json={"step_id": "CHECKOUT", "data": {"checkout": "done"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["lifecycle_state"] == "SUBSCRIPTION_ACTIVE"
        assert data["current_step"] is None
        assert data["next_route"] == "/dashboard"
        assert data["onboarding_complete"] is True
        assert data["progress_percentage"] == 100

    def test_resume_after_interruption(self, client):
        _fresh_api_service()
        uid = "user_resume"

        # Complete profile, leave
        client.post(
            "/api/v1/onboarding/profile",
            params={"user_id": uid},
            json={"display_name": "Resumer"},
        )

        # "Resume" — should be at workspace step
        resp = client.get("/api/v1/onboarding", params={"user_id": uid})
        assert resp.status_code == 200
        data = resp.json()
        assert data["lifecycle_state"] == "WORKSPACE_SETUP"
        assert data["current_step"] == "WORKSPACE_SETUP"
        assert data["completed_steps"] == ["PROFILE_SETUP"]

    def test_progress_query(self, client):
        _fresh_api_service()
        uid = "user_progress"

        resp = client.get("/api/v1/onboarding", params={"user_id": uid})
        data = resp.json()
        assert data["progress_percentage"] == 0
        assert data["total_steps"] == 5

        client.post(
            "/api/v1/onboarding/profile",
            params={"user_id": uid},
            json={"display_name": "Prog"},
        )
        resp = client.get("/api/v1/onboarding", params={"user_id": uid})
        data = resp.json()
        assert data["progress_percentage"] == 20
        assert len(data["completed_steps"]) == 1
        assert len(data["remaining_steps"]) == 4


# ═══════════════════════════════════════════════════════════════════════
# 6. Repository tests
# ═══════════════════════════════════════════════════════════════════════

class TestLifecycleRepository:

    @pytest.mark.asyncio
    async def test_save_and_find(self):
        repo = InMemoryLifecycleRepository()
        lc = UserLifecycle(user_id="u1")
        await repo.save(lc)

        found = await repo.find_by_user_id("u1")
        assert found is not None
        assert found.id == lc.id

        not_found = await repo.find_by_user_id("nonexistent")
        assert not_found is None

    @pytest.mark.asyncio
    async def test_get_and_delete(self):
        repo = InMemoryLifecycleRepository()
        lc = UserLifecycle(user_id="u2")
        await repo.save(lc)

        assert await repo.get(lc.id) is not None
        await repo.delete(lc.id)
        assert await repo.get(lc.id) is None


class TestOnboardingSessionRepository:

    @pytest.mark.asyncio
    async def test_find_active_by_user_id(self):
        repo = InMemoryOnboardingSessionRepository()
        s1 = OnboardingSession(user_id="u1", is_active=True)
        await repo.save(s1)

        found = await repo.find_active_by_user_id("u1")
        assert found is not None
        assert found.id == s1.id

    @pytest.mark.asyncio
    async def test_find_active_excludes_inactive(self):
        repo = InMemoryOnboardingSessionRepository()
        s1 = OnboardingSession(user_id="u1", is_active=False)
        await repo.save(s1)

        found = await repo.find_active_by_user_id("u1")
        assert found is None

    @pytest.mark.asyncio
    async def test_find_by_user_id(self):
        repo = InMemoryOnboardingSessionRepository()
        await repo.save(OnboardingSession(user_id="u1"))
        await repo.save(OnboardingSession(user_id="u1"))

        sessions = await repo.find_by_user_id("u1")
        assert len(sessions) == 2
