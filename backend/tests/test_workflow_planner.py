"""Unit tests for the Workflow Planner (Phase 3.4.1).

Tests are deterministic — no API calls, no mocks.
Tests only the planning logic.
"""

from services.workflow_models import (
    ActionType, RiskLevel, WorkflowPlan, WorkflowStep,
    PlanningInput, AlternativePlanPair,
)
from services.workflow_planner import (
    plan_workflow,
    _classify_objective,
    _extract_target,
)


EMPTY_SNAPSHOT = {
    "campaigns": [],
    "campaign_count": 0,
    "campaigns_ready": 0,
    "campaigns_draft_review": 0,
    "drafts": {"total": 0, "pending": 0, "approved": 0},
    "total_leads": 0,
    "jobs": {"running": [], "recently_completed": []},
    "memory": {},
    "timeline": [],
    "analysis": {
        "current_focus": {"focus": "Getting started", "action_type": "idle"},
        "workspace_health": {"overall_health": "empty"},
    },
}


def _snapshot_with(campaigns=None, drafts=None, runs=None, recent=None):
    s = dict(EMPTY_SNAPSHOT)
    campaigns = campaigns or []
    s["campaigns"] = campaigns
    s["campaign_count"] = len(campaigns)
    total_drafts = sum(c.get("pending_drafts", 0) + c.get("approved_drafts", 0) for c in campaigns)
    pending_drafts = sum(c.get("pending_drafts", 0) for c in campaigns)
    approved_drafts = sum(c.get("approved_drafts", 0) for c in campaigns)
    if drafts:
        pending_drafts = drafts.get("pending", pending_drafts)
        approved_drafts = drafts.get("approved", approved_drafts)
        total_drafts = drafts.get("total", pending_drafts + approved_drafts)
    s["drafts"] = {"total": total_drafts, "pending": pending_drafts, "approved": approved_drafts}
    s["total_leads"] = sum(c.get("lead_count", 0) for c in campaigns)
    s["jobs"]["running"] = runs or []
    s["jobs"]["recently_completed"] = recent or []
    s["campaigns_ready"] = sum(1 for c in campaigns if c.get("status") in ("ready", "ready_to_send"))
    s["campaigns_draft_review"] = sum(1 for c in campaigns if c.get("status") == "draft_review")
    active = [c for c in campaigns if c.get("status") not in ("completed", "archived")]
    s["analysis"]["current_focus"]["focus"] = f"{len(active)} active campaigns"
    if not active:
        s["analysis"]["current_focus"]["focus"] = "Getting started"
    return s


class TestClassification:
    def test_find_leads_objective(self):
        match_type, reason, score = _classify_objective("Find restaurants in Hyderabad")
        assert match_type == "find_leads"
        assert score > 0

    def test_create_campaign_objective(self):
        match_type, reason, score = _classify_objective("Create campaign for AI startups")
        assert match_type == "create_campaign"

    def test_finish_campaign_objective(self):
        match_type, reason, score = _classify_objective("Finish this campaign")
        assert match_type == "finish_campaign"

    def test_review_drafts_objective(self):
        match_type, reason, score = _classify_objective("Review my drafts")
        assert match_type == "review_drafts"

    def test_generate_drafts_objective(self):
        match_type, reason, score = _classify_objective("Generate drafts for this campaign")
        assert match_type == "generate_drafts"

    def test_find_similar_objective(self):
        match_type, reason, score = _classify_objective("Find companies like Blue Heron")
        assert match_type == "find_similar"

    def test_what_next_objective(self):
        match_type, reason, score = _classify_objective("What should I do next")
        assert match_type == "what_next"

    def test_launch_objective(self):
        match_type, reason, score = _classify_objective("Launch the campaign")
        assert match_type == "launch"

    def test_analyze_objective(self):
        match_type, reason, score = _classify_objective("Analyze my campaigns")
        assert match_type == "analyze"

    def test_rewrite_objective(self):
        match_type, reason, score = _classify_objective("Rewrite this draft")
        assert match_type == "rewrite"

    def test_default_fallback(self):
        match_type, reason, score = _classify_objective("Hello, how are you?")
        assert match_type == "what_next"


class TestTargetExtraction:
    def test_find_extraction(self):
        assert "restaurants in Hyderabad" in _extract_target("Find restaurants in Hyderabad")

    def test_search_extraction(self):
        assert "AI startups" in _extract_target("Search for AI startups")

    def test_like_extraction(self):
        target = _extract_target("Find companies like Blue Heron")
        assert "Blue Heron" in target

    def test_similar_extraction(self):
        target = _extract_target("Find similar companies to Acme Corp")
        assert "Acme Corp" in target

    def test_create_campaign_extraction(self):
        target = _extract_target("Create campaign for AI startups")
        assert "AI startups" in target


class TestEmptyWorkspace:
    def test_find_leads_on_empty_workspace(self):
        plan_pair = plan_workflow("Find restaurants", EMPTY_SNAPSHOT)
        assert isinstance(plan_pair, AlternativePlanPair)
        assert plan_pair.primary_plan.steps
        assert plan_pair.alternative_plan.steps
        assert plan_pair.confidence > 0
        first_action = plan_pair.primary_plan.steps[0].action_type
        assert first_action == ActionType.SEARCH_LEADS

    def test_create_campaign_on_empty_workspace(self):
        plan_pair = plan_workflow("Create campaign", EMPTY_SNAPSHOT)
        assert plan_pair.primary_plan.steps
        first_action = plan_pair.primary_plan.steps[0].action_type
        assert first_action == ActionType.SEARCH_LEADS

    def test_what_next_on_empty_workspace(self):
        plan_pair = plan_workflow("What should I do", EMPTY_SNAPSHOT)
        assert plan_pair.primary_plan.steps
        assert plan_pair.recommendation


class TestCampaignExists:
    def test_finish_ready_campaign(self):
        snapshot = _snapshot_with(campaigns=[{
            "id": "c1", "name": "Restaurant Outreach",
            "status": "ready_to_send", "lead_count": 10,
            "pending_drafts": 0, "approved_drafts": 5,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-07-12T00:00:00Z",
        }], drafts={"total": 5, "pending": 0, "approved": 5})
        plan_pair = plan_workflow("Finish this campaign", snapshot)
        assert plan_pair.primary_plan.goal == "Launch Restaurant Outreach"
        steps = plan_pair.primary_plan.steps
        assert steps[-1].action_type == ActionType.LAUNCH_CAMPAIGN

    def test_finish_draft_review_campaign(self):
        snapshot = _snapshot_with(campaigns=[{
            "id": "c1", "name": "Tech Conference",
            "status": "draft_review", "lead_count": 8,
            "pending_drafts": 3, "approved_drafts": 2,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-07-12T00:00:00Z",
        }], drafts={"total": 5, "pending": 3, "approved": 2})
        plan_pair = plan_workflow("Finish this campaign", snapshot)
        assert "review" in plan_pair.primary_plan.goal.lower()

    def test_finish_planning_campaign_with_leads(self):
        snapshot = _snapshot_with(campaigns=[{
            "id": "c1", "name": "Hyderabad Restaurants",
            "status": "planning", "lead_count": 15,
            "pending_drafts": 0, "approved_drafts": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-07-12T00:00:00Z",
        }])
        plan_pair = plan_workflow("Finish this campaign", snapshot)
        assert "draft" in plan_pair.primary_plan.goal.lower()

    def test_review_drafts_with_pending(self):
        snapshot = _snapshot_with(campaigns=[{
            "id": "c1", "name": "Test",
            "status": "draft_review", "lead_count": 5,
            "pending_drafts": 3, "approved_drafts": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-07-12T00:00:00Z",
        }], drafts={"total": 3, "pending": 3, "approved": 0})
        plan_pair = plan_workflow("Review my drafts", snapshot)
        steps = plan_pair.primary_plan.steps
        assert any(s.action_type == ActionType.REVIEW_DRAFTS for s in steps)

    def test_find_similar_companies(self):
        snapshot = _snapshot_with(campaigns=[{
            "id": "c1", "name": "Current Campaign",
            "status": "planning", "lead_count": 5,
            "pending_drafts": 0, "approved_drafts": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-07-12T00:00:00Z",
        }])
        plan_pair = plan_workflow("Find companies like Blue Heron", snapshot)
        assert plan_pair.alternative_plan.steps


class TestModelValidation:
    def test_workflow_step_defaults(self):
        step = WorkflowStep(title="Test step", action_type=ActionType.SEARCH_LEADS)
        assert step.id
        assert step.status.value == "pending"
        assert not step.approval_required
        assert step.retryable

    def test_workflow_step_approval(self):
        step = WorkflowStep(
            title="Launch", action_type=ActionType.LAUNCH_CAMPAIGN,
            approval_required=True,
        )
        assert step.approval_required

    def test_workflow_plan_defaults(self):
        plan = WorkflowPlan(goal="Test plan", reasoning="Because")
        assert plan.id
        assert plan.status.value == "draft"
        assert plan.estimated_steps == 0

    def test_workflow_plan_counts_steps(self):
        steps = [
            WorkflowStep(title="S1", action_type=ActionType.SEARCH_LEADS),
            WorkflowStep(title="S2", action_type=ActionType.CREATE_CAMPAIGN),
        ]
        plan = WorkflowPlan(goal="Test", reasoning="R", steps=steps)
        assert plan.estimated_steps == 2

    def test_planning_input(self):
        inp = PlanningInput(objective="Find leads", current_page="Discovery")
        assert inp.objective == "Find leads"
        assert inp.current_page == "Discovery"


class TestSnapshotsWithJobs:
    def test_running_job_detection(self):
        snapshot = _snapshot_with(runs=[{"id": "j1", "type": "search", "status": "running"}])
        plan_pair = plan_workflow("Find leads", snapshot)
        steps = plan_pair.primary_plan.steps
        assert any(s.action_type == ActionType.WAIT_FOR_USER for s in steps)


class TestEdgeCases:
    def test_empty_objective(self):
        plan_pair = plan_workflow("", EMPTY_SNAPSHOT)
        assert plan_pair.primary_plan.steps

    def test_very_long_objective(self):
        long_obj = "I want to find companies that are similar to Blue Heron " * 5
        plan_pair = plan_workflow(long_obj.strip(), EMPTY_SNAPSHOT)
        assert plan_pair.primary_plan.steps

    def test_generate_drafts_with_no_campaigns(self):
        plan_pair = plan_workflow("Generate drafts", EMPTY_SNAPSHOT)
        assert plan_pair.primary_plan.steps
