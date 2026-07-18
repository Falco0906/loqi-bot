import logging
from typing import Optional

from services.planner.planning_models import (
    Plan, Task, Approval, ApprovalRequirement,
)
from services.planner.strategies.strategy_base import Strategy, ApprovalRule

logger = logging.getLogger(__name__)


def apply_approval_rules(
    plan: Plan,
    strategy: Optional[Strategy] = None,
    confidence: float = 0.0,
    risk_level: str = "low",
) -> list[Approval]:
    approvals: list[Approval] = []

    strategy_rules: list[ApprovalRule] = []
    if strategy:
        strategy_rules = strategy.approval_rules(plan.tasks)

    for task in plan.tasks:
        requirement = _determine_approval_requirement(
            task, strategy_rules, confidence, risk_level,
        )
        task.approval = requirement

        if requirement != ApprovalRequirement.NONE:
            approval = Approval(
                task_id=task.id,
                requirement=requirement,
                status="pending",
            )
            approvals.append(approval)

    logger.info(
        "Applied approval rules: %d tasks require approval",
        len(approvals),
    )
    return approvals


def _determine_approval_requirement(
    task: Task,
    strategy_rules: list[ApprovalRule],
    confidence: float,
    risk_level: str,
) -> ApprovalRequirement:
    if risk_level == "high":
        if task.type.value in ("send_message", "send_email", "schedule_meeting", "escalate"):
            return ApprovalRequirement.REQUIRED

    if confidence < 0.4:
        if task.type.value in ("send_message", "send_email", "schedule_meeting"):
            return ApprovalRequirement.REQUIRED
        return ApprovalRequirement.RECOMMENDED

    if confidence < 0.7:
        if task.type.value in ("send_message", "send_email"):
            return ApprovalRequirement.RECOMMENDED

    for rule in strategy_rules:
        if rule.task_type == task.type or rule.task_type == task.type.value:
            if rule.requirement == "policy_mandated":
                return ApprovalRequirement.POLICY_MANDATED
            if rule.requirement == "required":
                return ApprovalRequirement.REQUIRED
            if rule.requirement == "recommended":
                if task.approval == ApprovalRequirement.NONE:
                    return ApprovalRequirement.RECOMMENDED

    return ApprovalRequirement.NONE
