"""Durable success-boundary regressions for core execution flows.

These tests deliberately exercise the production orchestration boundaries,
rather than treating a provider response as proof that the product operation
succeeded.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_search_job_is_not_created_when_discovery_insert_fails(monkeypatch):
    import services.discovery.service as discovery
    import services.workspace.state as workspace_state

    monkeypatch.setattr(workspace_state, "ensure_workspace", lambda _owner: "workspace-1")
    monkeypatch.setattr(discovery, "create_discovery", lambda *_args, **_kwargs: None)
    create_job = AsyncMock()
    monkeypatch.setattr(discovery.job_manager, "create_search_job", create_job)

    with pytest.raises(discovery.DiscoveryJobLifecycleError) as error:
        await discovery.create_search_run("owner-1", "cafe owners", initiation="manual")

    assert error.value.status_code == 503
    create_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovery_finalization_fails_when_canonical_lead_persistence_fails(monkeypatch):
    import services.discovery.service as discovery

    row = {"id": "discovery-1", "workspace_id": "workspace-1", "status": "searching", "query": "cafe owners"}

    class Query:
        def select(self, *_args): return self
        def eq(self, *_args): return self
        def limit(self, *_args): return self
        def update(self, *_args): return self
        def execute(self): return SimpleNamespace(data=[row])

    class Client:
        def table(self, *_args): return Query()

    class Storage:
        def get_search_results(self, _job_id):
            return [{"id": "provider-lead-1", "company": "Cafe One", "provider": "synthetic"}]

    marked: list[tuple[str, str, str]] = []
    monkeypatch.setattr(discovery, "get_supabase_client", lambda: Client())
    monkeypatch.setattr("services.job_engine.storage.JobStorage", Storage)
    async def persistence_failure(*_args, **_kwargs):
        raise RuntimeError("workspace_leads insert rejected")

    monkeypatch.setattr("services.workspace.state._normalize_lead", persistence_failure)
    monkeypatch.setattr(
        discovery,
        "mark_discovery_status",
        lambda *args, **kwargs: marked.append((*args, kwargs)),
    )

    completed = await discovery.finalize_discovery(
        SimpleNamespace(id="job-1", discovery_id="discovery-1", query="cafe owners")
    )

    assert completed is False
    assert marked and marked[-1][1] == "failed"
    assert "workspace_leads insert rejected" in marked[-1][2]


@pytest.mark.asyncio
async def test_discovery_finalization_normalizes_independent_leads_with_bounded_parallelism(monkeypatch):
    """Provider results keep their order while normalization avoids a serial tail."""
    import asyncio
    import services.discovery.service as discovery

    row = {
        "id": "discovery-1",
        "workspace_id": "workspace-1",
        "status": "searching",
        "query": "cafe owners",
    }

    class Query:
        def select(self, *_args): return self
        def eq(self, *_args): return self
        def limit(self, *_args): return self
        def update(self, *_args): return self
        def execute(self): return SimpleNamespace(data=[row])

    class Client:
        def table(self, *_args): return Query()

    class Storage:
        def get_search_results(self, _job_id):
            return [
                {"id": f"provider-{index}", "email": f"lead-{index}@example-{index}.com"}
                for index in range(4)
            ]

    active = 0
    peak_active = 0

    async def normalize(_workspace_id, lead):
        nonlocal active, peak_active
        active += 1
        peak_active = max(peak_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return f"workspace-{lead['id']}"

    captured: dict[str, object] = {}
    monkeypatch.setattr(discovery, "get_supabase_client", lambda: Client())
    monkeypatch.setattr("services.job_engine.storage.JobStorage", Storage)
    monkeypatch.setattr("services.workspace.state._normalize_lead", normalize)
    monkeypatch.setattr(
        discovery,
        "_link_leads",
        lambda _discovery_id, leads, workspace_lead_ids: captured.update(
            leads=leads, workspace_lead_ids=workspace_lead_ids,
        ) or len(workspace_lead_ids),
    )
    monkeypatch.setattr(discovery, "_link_companies", lambda *_args: 0)

    completed = await discovery.finalize_discovery(
        SimpleNamespace(id="job-1", discovery_id="discovery-1", query="cafe owners")
    )

    assert completed is True
    assert peak_active > 1
    assert captured["workspace_lead_ids"] == [
        "workspace-provider-0", "workspace-provider-1", "workspace-provider-2", "workspace-provider-3",
    ]


@pytest.mark.asyncio
async def test_discovery_finalization_serializes_contacts_at_the_same_company(monkeypatch):
    """Shared provider domains must not race global company unique indexes."""
    import asyncio
    import services.discovery.service as discovery

    row = {
        "id": "discovery-1", "workspace_id": "workspace-1",
        "status": "searching", "query": "saas founders",
    }

    class Query:
        def select(self, *_args): return self
        def eq(self, *_args): return self
        def limit(self, *_args): return self
        def update(self, *_args): return self
        def execute(self): return SimpleNamespace(data=[row])

    class Client:
        def table(self, *_args): return Query()

    class Storage:
        def get_search_results(self, _job_id):
            return [
                {
                    "lead_id": "founder-1", "email": "one@acme.example",
                    "company": "Acme", "company_website": "https://acme.example",
                    "provider": "synthetic",
                },
                {
                    "lead_id": "founder-2", "email": "two@acme.example",
                    "company": "Acme", "company_website": "https://acme.example",
                    "provider": "synthetic",
                },
            ]

    active = 0
    peak = 0

    async def normalize(_workspace_id, lead):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return f"workspace-{lead['lead_id']}"

    linked: dict[str, object] = {}
    monkeypatch.setattr(discovery, "get_supabase_client", lambda: Client())
    monkeypatch.setattr("services.job_engine.storage.JobStorage", Storage)
    monkeypatch.setattr("services.workspace.state._normalize_lead", normalize)
    monkeypatch.setattr(
        discovery, "_link_leads",
        lambda _id, _leads, ids: linked.update(ids=ids) or len(ids),
    )
    monkeypatch.setattr(discovery, "_link_companies", lambda *_args: 1)

    completed = await discovery.finalize_discovery(
        SimpleNamespace(id="job-1", discovery_id="discovery-1", query="saas founders")
    )

    assert completed is True
    assert peak == 1, "same-domain records must never normalize concurrently"
    assert linked["ids"] == ["workspace-founder-1", "workspace-founder-2"]


@pytest.mark.asyncio
async def test_discovery_finalization_skips_unidentifiable_provider_record(monkeypatch):
    """One malformed provider record must not discard valid canonical leads."""
    import services.discovery.service as discovery

    row = {
        "id": "discovery-1", "workspace_id": "workspace-1",
        "status": "searching", "query": "operations leaders",
    }

    class Query:
        def select(self, *_args): return self
        def eq(self, *_args): return self
        def limit(self, *_args): return self
        def update(self, *_args): return self
        def execute(self): return SimpleNamespace(data=[row])

    class Client:
        def table(self, *_args): return Query()

    class Storage:
        def get_search_results(self, _job_id):
            return [
                {"lead_id": "good-1", "email": "good@example.com", "provider": "synthetic"},
                {"name": "No stable identity", "provider": "synthetic"},
            ]

    captured: dict[str, object] = {}
    monkeypatch.setattr(discovery, "get_supabase_client", lambda: Client())
    monkeypatch.setattr("services.job_engine.storage.JobStorage", Storage)
    monkeypatch.setattr(
        "services.workspace.state._normalize_lead",
        AsyncMock(return_value="workspace-good-1"),
    )
    monkeypatch.setattr(
        discovery, "_link_leads",
        lambda _id, _leads, ids: captured.update(ids=ids) or len(ids),
    )
    monkeypatch.setattr(discovery, "_link_companies", lambda *_args: 0)

    completed = await discovery.finalize_discovery(
        SimpleNamespace(id="job-1", discovery_id="discovery-1", query="operations leaders")
    )

    assert completed is True
    assert captured["ids"] == ["workspace-good-1"]


@pytest.mark.asyncio
async def test_discovery_finalization_dedupes_provider_identity_before_canonical_write(monkeypatch):
    """Repeated provider results cannot create duplicate canonical links."""
    import services.discovery.service as discovery

    row = {
        "id": "discovery-1", "workspace_id": "workspace-1",
        "status": "searching", "query": "founders",
    }

    class Query:
        def select(self, *_args): return self
        def eq(self, *_args): return self
        def limit(self, *_args): return self
        def update(self, *_args): return self
        def execute(self): return SimpleNamespace(data=[row])

    class Client:
        def table(self, *_args): return Query()

    class Storage:
        def get_search_results(self, _job_id):
            lead = {"lead_id": "provider-1", "email": "ada@example.com", "provider": "synthetic"}
            return [lead, dict(lead)]

    normalize = AsyncMock(return_value="workspace-ada")
    captured: dict[str, object] = {}
    monkeypatch.setattr(discovery, "get_supabase_client", lambda: Client())
    monkeypatch.setattr("services.job_engine.storage.JobStorage", Storage)
    monkeypatch.setattr("services.workspace.state._normalize_lead", normalize)
    monkeypatch.setattr(
        discovery, "_link_leads",
        lambda _id, _leads, ids: captured.update(ids=ids) or len(ids),
    )
    monkeypatch.setattr(discovery, "_link_companies", lambda *_args: 0)

    completed = await discovery.finalize_discovery(
        SimpleNamespace(id="job-1", discovery_id="discovery-1", query="founders")
    )

    assert completed is True
    normalize.assert_awaited_once()
    assert captured["ids"] == ["workspace-ada"]


@pytest.mark.asyncio
async def test_strategy_enqueue_does_not_start_without_durable_job_metadata(monkeypatch):
    import services.campaigns.service as campaign_service

    monkeypatch.setattr(campaign_service, "persist_strategy_job_meta", AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as error:
        await campaign_service.enqueue_strategy_job(
            "session-1", "owner-1", "campaign-1", "Goal", {}, workspace_id="workspace-1",
        )

    assert error.value.status_code == 503
