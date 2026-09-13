"""Characterization tests for onboarding's initial Discovery launch."""
from __future__ import annotations

import pytest

from services.discovery.service import DiscoveryJobLifecycleError
from services.onboarding import api as onboarding_api
from services.onboarding.services import OnboardingService
from services.world_model import EventType


class _OnboardingRecorder:
    def __init__(self) -> None:
        self.saved: list[tuple[str, dict[str, object]]] = []

    async def save_wizard_data(self, user_id: str, data: dict[str, object]) -> dict[str, object]:
        self.saved.append((user_id, data))
        return data


@pytest.mark.asyncio
async def test_workspace_completion_invokes_the_onboarding_research_use_case(monkeypatch):
    calls = []

    class _CompletionService:
        async def create_workspace_and_finalize(self, user_id, data):
            calls.append(("finalize", user_id, data))
            return {"organization_id": "org-1"}

        async def get_wizard_data(self, user_id):
            calls.append(("wizard", user_id))
            return {"description": "Revenue intelligence"}

        async def launch_initial_research(self, user_id, wizard, session_token):
            calls.append(("research", user_id, wizard, session_token))

    service = _CompletionService()
    monkeypatch.setattr(onboarding_api, "_get_service", lambda: service)
    monkeypatch.setattr(onboarding_api, "_resolve_user_id", lambda *_args: _resolved_user("user-1"))

    result = await onboarding_api.create_workspace(
        object(),
        payload=onboarding_api.WorkspaceCreateRequest(
            workspace_name="Acme",
            session_token="session-1",
        ),
    )

    assert result == {"organization_id": "org-1"}
    assert calls == [
        ("finalize", "user-1", {"workspace_name": "Acme", "slug": "", "session_token": "session-1"}),
        ("wizard", "user-1"),
        ("research", "user-1", {"description": "Revenue intelligence"}, "session-1"),
    ]


async def _resolved_user(user_id: str) -> str:
    return user_id


@pytest.mark.asyncio
async def test_initial_research_launch_preserves_metadata_memory_and_started_event(monkeypatch):
    onboarding = _OnboardingRecorder()
    job_updates = []
    published = []
    memory = []
    timeline = []

    async def create_search_run(user_id, query, on_update):
        job_updates.append((user_id, query, on_update))
        return {"job_id": "job-1", "discovery_id": "discovery-1"}

    monkeypatch.setattr("services.discovery.service.create_search_run", create_search_run)
    monkeypatch.setattr("services.workspace_memory.record", lambda *args: memory.append(args))
    monkeypatch.setattr("services.workspace_timeline.record_search_started", lambda *args: timeline.append(args))
    monkeypatch.setattr("services.world_model.publish", lambda *args, **kwargs: published.append((args, kwargs)))

    await OnboardingService.launch_initial_research(
        onboarding,
        "user-1",
        {"companyDescription": "Revenue intelligence", "idealCustomer": "CTOs"},
        "session-1",
    )

    assert onboarding.saved == [
        ("user-1", {"initial_research_launched": True}),
        ("user-1", {"initial_research_job_id": "job-1", "initial_research_session_token": "session-1"}),
    ]
    assert job_updates[0][:2] == ("user-1", "Revenue intelligence for CTOs")
    assert memory == [
        ("session-1", "company_description", "Revenue intelligence"),
        ("session-1", "ideal_customer", "CTOs"),
    ]
    assert timeline == [("session-1", "Revenue intelligence for CTOs")]
    assert published[-1][0][1] is EventType.WORKFLOW_STARTED
    assert published[-1][0][2] == {
        "workflow_type": "research",
        "job_id": "job-1",
        "query": "Revenue intelligence for CTOs",
        "status": "queued",
    }


@pytest.mark.asyncio
async def test_initial_research_failure_resets_marker_and_emits_failure(monkeypatch):
    onboarding = _OnboardingRecorder()
    published = []

    async def create_search_run(*_args, **_kwargs):
        raise DiscoveryJobLifecycleError(503, "Discovery could not be persisted")

    monkeypatch.setattr("services.discovery.service.create_search_run", create_search_run)
    monkeypatch.setattr("services.world_model.publish", lambda *args, **kwargs: published.append((args, kwargs)))

    await OnboardingService.launch_initial_research(
        onboarding,
        "user-1", {"description": "Revenue intelligence"}, "session-1",
    )

    assert onboarding.saved == [
        ("user-1", {"initial_research_launched": True}),
        ("user-1", {"initial_research_launched": False}),
    ]
    assert published[-1][0][1] is EventType.WORKFLOW_FAILED
    assert published[-1][0][2]["error"] == "Unable to create the initial research job"


@pytest.mark.asyncio
async def test_initial_research_is_idempotent_and_requires_research_inputs(monkeypatch):
    onboarding = _OnboardingRecorder()
    await OnboardingService.launch_initial_research(
        onboarding, "user-1", {"initial_research_launched": True}, "session-1",
    )
    assert onboarding.saved == []

    with pytest.raises(ValueError, match="Onboarding did not contain research inputs"):
        await OnboardingService.launch_initial_research(onboarding, "user-1", {}, "session-1")
