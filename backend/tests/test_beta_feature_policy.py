"""Beta policy tests: deferred capability code remains present but unreachable."""

import asyncio

import pytest
from fastapi import HTTPException

from services.capabilities.beta import beta_feature_enabled, beta_features
import services.campaigns.service as campaign_service
from services.conversations.service import send_follow_up
from services.discovery.service import DiscoveryJobLifecycleError, create_search_run
from services.outbound.service import schedule_outbound_draft, send_outbound_draft
from services.workflows.api import _require_beta_workflow_execution


def test_beta_policy_exposes_intelligence_and_defers_autonomy():
    features = beta_features()

    assert features["lead_search"] is True
    assert features["lead_analysis"] is True
    assert features["lead_scoring"] is True
    assert features["strategy_generation"] is True
    assert features["outreach_generation"] is True
    assert beta_feature_enabled("autonomous_lead_sourcing") is False
    assert beta_feature_enabled("outbound_delivery") is False
    assert beta_feature_enabled("automated_followups") is False
    assert beta_feature_enabled("autonomous_workflows") is False


def test_discovery_sourcing_is_rejected_before_any_persistence_work():
    with pytest.raises(DiscoveryJobLifecycleError) as exc:
        asyncio.run(create_search_run("owner", "workspace", "source prospects"))

    assert exc.value.status_code == 403
    assert "not available in Loqi Beta" in exc.value.detail


def test_direct_outbound_operations_are_rejected_before_request_resolution():
    with pytest.raises(HTTPException) as send_exc:
        asyncio.run(send_outbound_draft(None, "draft-id"))
    with pytest.raises(HTTPException) as schedule_exc:
        asyncio.run(schedule_outbound_draft(None, "draft-id", "2030-01-01T00:00:00Z"))

    assert send_exc.value.status_code == 403
    assert schedule_exc.value.status_code == 403


def test_campaign_launch_and_automated_followup_are_rejected_before_side_effects(monkeypatch):
    monkeypatch.setattr(campaign_service, "load_campaigns", lambda *_args, **_kwargs: [{"id": "campaign-a", "status": "draft"}])

    with pytest.raises(HTTPException) as launch_exc:
        asyncio.run(campaign_service.update_campaign(
            "session", "owner", "workspace-a", "campaign-a", {"status": "completed"},
        ))
    with pytest.raises(HTTPException) as followup_exc:
        asyncio.run(send_follow_up("conversation-a", "owner", object()))

    assert launch_exc.value.status_code == 403
    assert followup_exc.value.status_code == 403


def test_legacy_workflow_execution_is_rejected_at_the_api_boundary():
    with pytest.raises(HTTPException) as exc:
        _require_beta_workflow_execution()

    assert exc.value.status_code == 403
