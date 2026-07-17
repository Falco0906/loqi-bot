from enum import Enum
from uuid import uuid4
from pydantic import BaseModel


class PlanStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActionType(str, Enum):
    SEARCH_LEADS = "search_leads"
    EXPAND_SEARCH = "expand_search"
    FILTER_LEADS = "filter_leads"
    SELECT_LEADS = "select_leads"
    CREATE_CAMPAIGN = "create_campaign"
    UPDATE_CAMPAIGN = "update_campaign"
    GENERATE_DRAFTS = "generate_drafts"
    REVIEW_DRAFTS = "review_drafts"
    REWRITE_DRAFTS = "rewrite_drafts"
    LAUNCH_CAMPAIGN = "launch_campaign"
    NAVIGATE = "navigate"
    ANALYZE_CAMPAIGN = "analyze_campaign"
    WAIT_FOR_USER = "wait_for_user"
    CREATE_REPLY_DRAFT = "create_reply_draft"
    UPDATE_REPLY_DRAFT = "update_reply_draft"
    SEND_REPLY = "send_reply"
    SCHEDULE_REPLY = "schedule_reply"
    DELETE_DRAFT = "delete_draft"


class WorkflowStep(BaseModel):
    id: str = ""
    title: str
    description: str = ""
    action_type: ActionType
    required_inputs: list[str] = []
    dependencies: list[str] = []
    estimated_duration: str = ""
    approval_required: bool = False
    retryable: bool = True
    status: StepStatus = StepStatus.PENDING

    def model_post_init(self, __context) -> None:
        if not self.id:
            self.id = str(uuid4())[:8]


class WorkflowPlan(BaseModel):
    id: str = ""
    goal: str
    reasoning: str
    estimated_duration: str = ""
    estimated_steps: int = 0
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    status: PlanStatus = PlanStatus.DRAFT
    steps: list[WorkflowStep] = []

    def model_post_init(self, __context) -> None:
        if not self.id:
            self.id = str(uuid4())[:8]
        if not self.estimated_steps and self.steps:
            self.estimated_steps = len(self.steps)


class AlternativePlanPair(BaseModel):
    primary_plan: WorkflowPlan
    alternative_plan: WorkflowPlan
    recommendation: str = ""
    confidence: int = 0


class PlanningInput(BaseModel):
    objective: str
    current_page: str = "unknown"


APPROVAL_ACTIONS: set[str] = {
    ActionType.LAUNCH_CAMPAIGN,
    ActionType.CREATE_CAMPAIGN,
    ActionType.REVIEW_DRAFTS,
    ActionType.SELECT_LEADS,
}

ACTION_DURATIONS: dict[ActionType, str] = {
    ActionType.SEARCH_LEADS: "30-60s",
    ActionType.EXPAND_SEARCH: "30-60s",
    ActionType.FILTER_LEADS: "~10s",
    ActionType.SELECT_LEADS: "~10s",
    ActionType.CREATE_CAMPAIGN: "~20s",
    ActionType.UPDATE_CAMPAIGN: "~10s",
    ActionType.GENERATE_DRAFTS: "2-5min",
    ActionType.REVIEW_DRAFTS: "~2min",
    ActionType.REWRITE_DRAFTS: "~30s",
    ActionType.LAUNCH_CAMPAIGN: "~10s",
    ActionType.NAVIGATE: "instant",
    ActionType.ANALYZE_CAMPAIGN: "~30s",
    ActionType.WAIT_FOR_USER: "until ready",
}
