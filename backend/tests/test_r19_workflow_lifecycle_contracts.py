"""Characterization coverage for legacy web-workflow lifecycle adapters."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import services.workflows.api as workflow_api
import services.workflows.service as workflow_service
from services.workflows.runtime import clear as clear_runtimes, create_runtime
from services.world_model import EventType as WMEventType


SESSION_TOKEN = "workflow-lifecycle-session"
WORKFLOW_ID = "workflow-lifecycle-id"


def _request() -> SimpleNamespace:
    return SimpleNamespace(headers={"authorization": f"Bearer {SESSION_TOKEN}"})


def _runtime(status: str) -> SimpleNamespace:
    return SimpleNamespace(
        workflow_id=WORKFLOW_ID,
        status=SimpleNamespace(value=status),
        summary=lambda: {"workflow_id": WORKFLOW_ID, "status": status},
    )


@pytest.fixture(autouse=True)
def _reset_runtime_state():
    clear_runtimes()
    yield
    clear_runtimes()


@pytest.mark.asyncio
async def test_execute_workflow_preserves_response_and_started_event(monkeypatch):
    captured: dict[str, object] = {}

    def execute(plan, session_token):
        captured["plan"] = plan
        captured["session_token"] = session_token
        return _runtime("running")

    monkeypatch.setattr(workflow_service, "execute_runtime", execute)
    monkeypatch.setattr(workflow_service, "calculate_progress", lambda _runtime: {"percentage": 0})
    monkeypatch.setattr(
        workflow_service,
        "publish",
        lambda session_token, event_type, data, actor="": captured.update(
            event=(session_token, event_type, data, actor)
        ),
    )

    payload = workflow_api.ExecuteWorkflowRequest(
        plan_id="plan-1",
        goal="Review drafts",
        reasoning="Drafts need review",
        estimated_duration="1m",
        risk_level="medium",
        requires_approval=True,
        steps=[],
    )
    result = await workflow_api.execute_workflow_endpoint("ignored", payload, _request())

    assert captured["session_token"] == SESSION_TOKEN
    assert captured["plan"].id == "plan-1"
    assert result == {
        "ok": True,
        "workflow_id": WORKFLOW_ID,
        "status": "running",
        "progress": {"percentage": 0},
        "runtime": {"workflow_id": WORKFLOW_ID, "status": "running"},
    }
    assert captured["event"] == (
        SESSION_TOKEN,
        WMEventType.WORKFLOW_STARTED,
        {
            "workflow_id": WORKFLOW_ID,
            "goal": "Review drafts",
            "step_count": 0,
            "risk_level": "medium",
            "requires_approval": True,
        },
        "user",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route_name,executor_name,status,event_type,includes_runtime",
    [
        ("approve_workflow_step", "approve_runtime", "running", WMEventType.WORKFLOW_APPROVED, True),
        ("pause_workflow_endpoint", "pause_runtime", "paused", WMEventType.WORKFLOW_PAUSED, False),
        ("resume_workflow_endpoint", "resume_runtime", "running", WMEventType.WORKFLOW_RESUMED, False),
        ("cancel_workflow_endpoint", "cancel_runtime", "cancelled", WMEventType.WORKFLOW_CANCELLED, False),
    ],
)
async def test_lifecycle_commands_preserve_response_progress_and_events(
    monkeypatch,
    route_name,
    executor_name,
    status,
    event_type,
    includes_runtime,
):
    create_runtime({"goal": "Review drafts", "steps": []}, SESSION_TOKEN, WORKFLOW_ID)
    published: list[tuple] = []
    monkeypatch.setattr(workflow_service, executor_name, lambda _workflow_id: _runtime(status))
    monkeypatch.setattr(workflow_service, "calculate_progress", lambda _runtime: {"percentage": 50})
    monkeypatch.setattr(workflow_service, "publish", lambda *args, **kwargs: published.append((args, kwargs)))

    result = await getattr(workflow_api, route_name)("ignored", WORKFLOW_ID, _request())

    expected = {"ok": True, "workflow_id": WORKFLOW_ID, "status": status}
    if status != "cancelled":
        expected["progress"] = {"percentage": 50}
    if includes_runtime:
        expected["runtime"] = {"workflow_id": WORKFLOW_ID, "status": status}
    assert result == expected
    assert published == [
        (
            (SESSION_TOKEN, event_type, {"workflow_id": WORKFLOW_ID, "status": status}),
            {"actor": "user"},
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route_name,executor_name",
    [
        ("approve_workflow_step", "approve_runtime"),
        ("pause_workflow_endpoint", "pause_runtime"),
        ("resume_workflow_endpoint", "resume_runtime"),
        ("cancel_workflow_endpoint", "cancel_runtime"),
    ],
)
async def test_lifecycle_transition_errors_remain_http_400(monkeypatch, route_name, executor_name):
    create_runtime({"goal": "Review drafts", "steps": []}, SESSION_TOKEN, WORKFLOW_ID)

    def invalid_transition(_workflow_id):
        raise ValueError("Workflow cannot transition")

    monkeypatch.setattr(workflow_service, executor_name, invalid_transition)
    with pytest.raises(HTTPException) as error:
        await getattr(workflow_api, route_name)("ignored", WORKFLOW_ID, _request())

    assert error.value.status_code == 400
    assert error.value.detail == "Workflow cannot transition"
