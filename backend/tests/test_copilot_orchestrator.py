"""Phase 4 regressions for bounded, grounded Copilot tool orchestration."""

from __future__ import annotations

import asyncio

import pytest

from services.copilot_orchestrator import (
    MAX_PLAN_STEPS,
    build_plan,
    execute_copilot_plan,
)


@pytest.mark.asyncio
async def test_sequences_tools_and_carries_only_canonical_result_identifiers():
    calls: list[tuple[str, dict]] = []

    async def execute(tool: str, decision: dict):
        calls.append((tool, decision))
        if tool == "campaign.read":
            return {"ok": True, "status": "completed", "result": {"campaign": {"id": "campaign-canonical"}}}
        assert tool == "outreach.drafts.read"
        assert decision["campaign_id"] == "campaign-canonical"
        return {"ok": True, "status": "completed", "result": {"drafts": []}}

    result = await execute_copilot_plan({
        "plan": [
            {"action": "campaign.read", "campaign_id": "campaign-requested"},
            {"action": "outreach.drafts.read"},
        ],
        "page_context": {},
    }, execute)

    assert result["ok"] is True
    assert [tool for tool, _ in calls] == ["campaign.read", "outreach.drafts.read"]


@pytest.mark.asyncio
async def test_replans_from_actual_unavailable_tool_result_to_safe_read_fallback():
    calls: list[str] = []

    async def execute(tool: str, _decision: dict):
        calls.append(tool)
        if tool == "analytics.campaign.summary":
            return {"ok": False, "status": "unavailable", "reason": "No selected campaign."}
        return {"ok": True, "status": "completed", "result": {"metrics": {"campaign_count": 2}}}

    result = await execute_copilot_plan({
        "plan": [{"action": "analytics.campaign.summary"}],
    }, execute)

    assert result["ok"] is True
    assert calls == ["analytics.campaign.summary", "analytics.workspace.summary"]
    assert result["steps"][1]["source"] == "fallback:analytics.campaign.summary"


@pytest.mark.asyncio
async def test_mutation_plan_requires_authoritative_final_verification():
    calls: list[tuple[str, dict]] = []

    async def execute(tool: str, decision: dict):
        calls.append((tool, decision))
        if tool == "lead.rank":
            return {"ok": True, "status": "completed", "result": {"leads": [{"id": "lead-1"}]}}
        if tool == "lead.save":
            assert decision["lead_ids"] == ["lead-1"]
            return {"ok": True, "status": "completed", "result": {"saved_ids": ["lead-1"]}}
        assert tool == "lead.read"
        return {"ok": True, "status": "completed", "result": {"leads": [{"id": "lead-1", "status": "saved"}]}}

    result = await execute_copilot_plan({
        "plan": [{"action": "lead.rank"}, {"action": "lead.save"}],
    }, execute)

    assert result["ok"] is True
    assert [tool for tool, _ in calls] == ["lead.rank", "lead.save", "lead.read"]
    assert result["steps"][-1]["source"] == "verify:lead.save"


@pytest.mark.asyncio
async def test_confirmation_failure_stops_plan_before_mutation_or_verification():
    calls: list[str] = []

    async def execute(tool: str, _decision: dict):
        calls.append(tool)
        if tool == "lead.rank":
            return {"ok": True, "status": "completed", "result": {"leads": [{"id": "lead-1"}]}}
        return {"ok": False, "status": "confirmation_required", "reason": "Confirm save."}

    result = await execute_copilot_plan({
        "plan": [{"action": "lead.rank"}, {"action": "lead.save"}],
    }, execute)

    assert result["ok"] is False
    assert result["status"] == "confirmation_required"
    assert calls == ["lead.rank", "lead.save"]


@pytest.mark.asyncio
async def test_async_job_acceptance_stops_later_steps_for_phase3_monitoring():
    calls: list[str] = []

    async def execute(tool: str, _decision: dict):
        calls.append(tool)
        if tool == "campaign.read":
            return {"ok": True, "status": "completed", "result": {"campaign": {"id": "campaign-1"}}}
        return {
            "ok": True,
            "status": "accepted",
            "operation": {"kind": "search_discovery", "job_id": "job-1", "discovery_id": "discovery-1"},
        }

    result = await execute_copilot_plan({
        "plan": [{"action": "campaign.read"}, {"action": "discovery.search"}],
    }, execute)

    assert result["ok"] is True
    assert result["status"] == "accepted"
    assert result["operation"]["job_id"] == "job-1"
    assert calls == ["campaign.read", "discovery.search"]


def test_plan_bounds_and_model_workspace_fields_are_rejected_or_ignored():
    plan, error = build_plan({
        "plan": [{"action": "campaign.list", "workspace_id": "workspace-attacker"}],
    })
    assert error is None
    assert plan[0].inputs == {}

    _, too_many_error = build_plan({
        "plan": [{"action": "campaign.list"}] * (MAX_PLAN_STEPS + 1),
    })
    assert "step limit" in str(too_many_error)

    _, async_order_error = build_plan({
        "plan": [{"action": "discovery.search"}, {"action": "campaign.list"}],
    })
    assert "final planned step" in str(async_order_error)


@pytest.mark.asyncio
async def test_time_limit_never_reports_success():
    async def slow_execute(_tool: str, _decision: dict):
        await asyncio.sleep(0.05)
        return {"ok": True, "status": "completed", "result": {}}

    result = await execute_copilot_plan(
        {"plan": [{"action": "campaign.list"}]},
        slow_execute,
        time_limit_seconds=0.001,
    )

    assert result["ok"] is False
    assert result["status"] == "time_limit_reached"
