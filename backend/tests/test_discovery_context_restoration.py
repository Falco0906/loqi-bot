"""Offline context snapshots use existing Discovery/job persistence only."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.discovery import api, service
from services.leads import generation
from services.job_engine.models import Job, JobStatus


def test_search_filter_snapshot_is_written_on_existing_discovery_row(monkeypatch):
    inserted = []

    class Query:
        def insert(self, value):
            inserted.append(value)
            return self
        def execute(self):
            return SimpleNamespace(data=[{**inserted[-1], "id": "run"}])

    monkeypatch.setattr(service, "get_supabase_client", lambda: SimpleNamespace(table=lambda name: Query() if name == "discoveries" else pytest.fail("unexpected table")))
    row = service.create_discovery("selected", "actor", "founders", ui_filters={"location": "India", "title": "Founder"})
    assert row["workspace_id"] == "selected"
    assert row["metadata"] == {"ui_filters": {"location": "India", "title": "Founder"}}
    assert row["query"] == "founders"
    # Existing callers still get the previous default payload.
    assert service.create_discovery("selected", "actor", "founders")["metadata"] == {}


@pytest.mark.asyncio
async def test_authenticated_search_snapshot_uses_authorized_workspace(monkeypatch):
    monkeypatch.setattr(api, "_authorized_workspace", AsyncMock(return_value=("actor", "session", "selected")))
    start = AsyncMock(return_value={"discovery_id": "run", "job_id": "job"})
    monkeypatch.setattr(api, "create_search_run", start)
    result = await api.create_discovery_endpoint(api.CreateDiscoveryRequest(query="founders", initiation="manual", filters={"industry": "software"}), SimpleNamespace())
    assert result["discovery_id"] == "run"
    start.assert_awaited_once_with("actor", "founders", "session", workspace_id="selected", initiation="manual", ui_filters={"industry": "software"})


@pytest.mark.asyncio
async def test_unauthorized_search_never_creates_context_or_job(monkeypatch):
    monkeypatch.setattr(api, "_authorized_workspace", AsyncMock(side_effect=HTTPException(404, "Workspace not found")))
    start = AsyncMock()
    monkeypatch.setattr(api, "create_search_run", start)
    with pytest.raises(HTTPException):
        await api.create_discovery_endpoint(api.CreateDiscoveryRequest(query="founders"), SimpleNamespace())
    start.assert_not_awaited()


@pytest.mark.parametrize("filters", [{"unknown": "value"}, {"location": "x" * 201}])
def test_invalid_snapshot_filters_are_rejected(filters):
    with pytest.raises(ValidationError):
        api.CreateDiscoveryRequest(query="founders", filters=filters)


@pytest.mark.asyncio
async def test_history_read_is_workspace_scoped_and_missing_is_not_empty_success(monkeypatch):
    monkeypatch.setattr(api, "_authorized_workspace", AsyncMock(return_value=("actor", "session", "selected")))
    calls = []

    def read(identity, workspace):
        calls.append((identity, workspace))
        return {"id": identity, "query": "founders", "metadata": {"ui_filters": {"location": "India"}}, "discovery_leads": [{"workspace_lead": {"id": "canonical"}}]} if identity == "saved" else None

    monkeypatch.setattr(api, "get_discovery", read)
    result = await api.get_discovery_endpoint("saved", SimpleNamespace())
    assert result["discovery"]["discovery_leads"][0]["workspace_lead"]["id"] == "canonical"
    for identity in ["missing", "foreign"]:
        with pytest.raises(HTTPException) as caught:
            await api.get_discovery_endpoint(identity, SimpleNamespace())
        assert caught.value.status_code == 404
    assert calls == [("saved", "selected"), ("missing", "selected"), ("foreign", "selected")]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.COMPLETED])
async def test_read_only_generation_recovery_exposes_original_selection(monkeypatch, status):
    job = Job(id="job", type="lead_strategy", user_id="actor", workspace_id="selected", status=status, payload={"lead_ids": ["a", "b"]}, result={"results": []})
    monkeypatch.setattr(generation.job_manager, "_storage", SimpleNamespace(get_job=lambda *_args, **_kwargs: job))
    result = await generation.generation_status("selected", "actor", "job")
    assert result["lead_ids"] == ["a", "b"]
    with pytest.raises(HTTPException) as caught:
        await generation.generation_status("other", "actor", "job")
    assert caught.value.status_code == 404
