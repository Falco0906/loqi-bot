"""Planning Engine.

Consumes Reasoning Results → produces structured Execution Plans.
Never executes actions, generates replies, or calls providers.
"""

from .exceptions import (
    PlanningError, PlanningValidationError, PlanningStrategyError,
    PlanningGraphError, PlanningSchedulingError, PlanningPipelineError,
)
from .payloads import (
    TaskPayload, MessagePayload, WaitForReplyPayload, WaitDurationPayload,
    AnalyzeReplyPayload, EscalatePayload, UpdateCRMPayload,
    RequestApprovalPayload, ScheduleMeetingPayload,
    BranchPayload, JoinPayload,
    get_payload_class, register_payload_class,
)
from .planning_models import (
    Plan, PlanGoal, Task, Trigger, Branch, Dependency, Schedule, Approval,
    PlanStatus, TaskStatus, TaskType, TriggerType, BranchCondition,
    ApprovalRequirement, DependencyType,
    PLANNER_VERSION,
)
from .planning_pipeline import PlanningPipeline, get_pipeline, generate_plan
from .plan_validator import validate_plan, ValidationResult, ValidationIssue
from .task_generator import generate_tasks
from .dependency_builder import build_dependencies, validate_dag
from .scheduling_engine import apply_scheduling
from .branching_engine import apply_branching
from .approval_engine import apply_approval_rules
from .strategies.strategy_base import Strategy
from .strategies.planning_registry import (
    register_strategy, get_strategy, list_strategies, select_strategy,
)

__all__ = [
    # Exceptions
    "PlanningError", "PlanningValidationError", "PlanningStrategyError",
    "PlanningGraphError", "PlanningSchedulingError", "PlanningPipelineError",
    # Payloads
    "TaskPayload", "MessagePayload", "WaitForReplyPayload", "WaitDurationPayload",
    "AnalyzeReplyPayload", "EscalatePayload", "UpdateCRMPayload",
    "RequestApprovalPayload", "ScheduleMeetingPayload",
    "BranchPayload", "JoinPayload",
    "get_payload_class", "register_payload_class",
    # Models
    "Plan", "PlanGoal", "Task", "Trigger", "Branch", "Dependency",
    "Schedule", "Approval",
    "PlanStatus", "TaskStatus", "TaskType", "TriggerType",
    "BranchCondition", "ApprovalRequirement", "DependencyType",
    "PLANNER_VERSION",
    # Pipeline / stages
    "PlanningPipeline", "get_pipeline", "generate_plan",
    "validate_plan", "ValidationResult", "ValidationIssue",
    "generate_tasks", "build_dependencies", "validate_dag",
    "apply_scheduling", "apply_branching", "apply_approval_rules",
    "Strategy",
    "register_strategy", "get_strategy", "list_strategies", "select_strategy",
]
