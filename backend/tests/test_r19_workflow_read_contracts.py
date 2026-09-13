"""Characterization coverage for legacy web-workflow read adapters."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import main as main_module
import services.workflows.api as workflow_api
from services.workflows.events import clear as clear_events, emit, EventType
from services.workflows.runtime import clear as clear_runtimes, create_runtime


SESSION_A = "workflow-session-a"
SESSION_B = "workflow-session-b"


def _request(session_token: str) -> SimpleNamespace:
    return SimpleNamespace(headers={"authorization": f"Bearer {session_token}"})


@pytest.fixture(autouse=True)
def _reset_workflow_runtime():
    clear_runtimes()
    clear_events()
    yield
    clear_runtimes()
    clear_events()


@pytest.mark.asyncio
async def test_workflow_read_response_envelopes_are_preserved():
    runtime = create_runtime({"goal": "Review drafts", "steps": []}, SESSION_A, "workflow-a")
    emit(runtime.workflow_id, EventType.WORKFLOW_STARTED, "Started")
    emit(runtime.workflow_id, EventType.LOG, "Second event")
    create_runtime({"goal": "Other workspace", "steps": []}, SESSION_B, "workflow-b")

    status = await workflow_api.get_workflow_status("ignored", runtime.workflow_id, _request(SESSION_A))
    events = await workflow_api.get_workflow_events_endpoint("ignored", runtime.workflow_id, _request(SESSION_A))
    polling = await workflow_api.workflow_events_after(
        "ignored", runtime.workflow_id, after=1, request=_request(SESSION_A),
    )
    listing = await workflow_api.list_workflows("ignored", _request(SESSION_A))
    history = await workflow_api.workflow_history("ignored", request=_request(SESSION_A))

    assert set(status) == {"ok", "runtime", "progress"}
    assert status["runtime"]["workflow_id"] == runtime.workflow_id
    assert set(events) == {"ok", "events"}
    assert [event["sequence_number"] for event in events["events"]] == [2, 1]
    assert set(polling) == {"ok", "events", "latest_sequence"}
    assert polling["latest_sequence"] == 2
    assert [event["sequence_number"] for event in polling["events"]] == [2]
    assert set(listing) == {"ok", "workflows", "active"}
    assert [workflow["workflow_id"] for workflow in listing["workflows"]] == [runtime.workflow_id]
    assert set(history) == {"ok", "history"}
    assert [workflow["workflow_id"] for workflow in history["history"]] == [runtime.workflow_id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route_name,args",
    [
        ("get_workflow_status", ("ignored", "workflow-b")),
        ("get_workflow_events_endpoint", ("ignored", "workflow-b")),
        ("workflow_events_after", ("ignored", "workflow-b")),
    ],
)
async def test_workflow_read_routes_hide_foreign_workflows(route_name, args):
    create_runtime({"goal": "Private", "steps": []}, SESSION_B, "workflow-b")

    route = getattr(workflow_api, route_name)
    with pytest.raises(HTTPException) as error:
        await route(*args, request=_request(SESSION_A))

    assert error.value.status_code == 404
    assert error.value.detail == "Workflow not found"


def test_history_route_is_not_consumed_as_a_dynamic_workflow_id(client):
    """``/history`` must return its history envelope, not status-route output."""
    create_runtime({"goal": "Review drafts", "steps": []}, SESSION_A, "workflow-a")

    response = client.get(
        f"/api/web/session/{SESSION_A}/workflows/history",
        headers={"Authorization": f"Bearer {SESSION_A}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"ok", "history"}
    assert body["history"][0]["workflow_id"] == "workflow-a"
