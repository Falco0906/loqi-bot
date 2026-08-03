from __future__ import annotations

from typing import Any

from services.intentions.models import IntentionType, PriorityLevel, ReasonCode


class PolicyResult:
    """Output of a single policy evaluation."""
    def __init__(
        self,
        intention_type: IntentionType,
        reason_code: ReasonCode,
        priority: PriorityLevel,
        confidence: float,
        blocking: bool,
        detail: str = "",
    ) -> None:
        self.intention_type = intention_type
        self.reason_code = reason_code
        self.priority = priority
        self.confidence = confidence
        self.blocking = blocking
        self.detail = detail


class Policy:
    """A single deterministic policy rule.

    Each policy inspects a slice of workspace state/signals/reasoning
    and returns a PolicyResult or None if the rule doesn't apply.
    """
    name: str = ""

    def evaluate(self, signals: dict[str, Any], reasoning: dict[str, Any]) -> PolicyResult | None:
        raise NotImplementedError


# ── Concrete Policies ────────────────────────────────────────────


class CampaignReadyPolicy(Policy):
    """Campaign is fully prepared and waiting for user approval to launch."""
    name = "campaign_ready"

    def evaluate(self, signals: dict[str, Any], reasoning: dict[str, Any]) -> PolicyResult | None:
        ready_campaigns = signals.get("campaigns_ready_to_launch", 0)
        if ready_campaigns <= 0:
            return None
        return PolicyResult(
            intention_type=IntentionType.ASK_USER,
            reason_code=ReasonCode.CAMPAIGN_READY,
            priority=PriorityLevel.HIGH,
            confidence=0.95,
            blocking=True,
            detail=f"{ready_campaigns} campaign(s) ready to launch",
        )


class DraftReviewRequiredPolicy(Policy):
    """Drafts exist that need human review before sending."""
    name = "draft_review_required"

    def evaluate(self, signals: dict[str, Any], reasoning: dict[str, Any]) -> PolicyResult | None:
        pending = signals.get("drafts_pending_review", 0)
        if pending <= 0:
            return None
        return PolicyResult(
            intention_type=IntentionType.RECOMMEND_ACTION,
            reason_code=ReasonCode.DRAFT_REVIEW_REQUIRED,
            priority=PriorityLevel.NORMAL,
            confidence=0.9,
            blocking=False,
            detail=f"{pending} draft(s) need review",
        )


class NewReplyReceivedPolicy(Policy):
    """A new reply has arrived that needs attention."""
    name = "new_reply"

    def evaluate(self, signals: dict[str, Any], reasoning: dict[str, Any]) -> PolicyResult | None:
        unread = signals.get("unread_replies", 0)
        if unread <= 0:
            return None
        urgent = signals.get("urgent_replies", 0)
        if urgent > 0:
            return PolicyResult(
                intention_type=IntentionType.ASK_USER,
                reason_code=ReasonCode.NEW_REPLY_RECEIVED,
                priority=PriorityLevel.HIGH,
                confidence=0.85,
                blocking=False,
                detail=f"{urgent} urgent reply(ies) need attention",
            )
        return PolicyResult(
            intention_type=IntentionType.RECOMMEND_ACTION,
            reason_code=ReasonCode.NEW_REPLY_RECEIVED,
            priority=PriorityLevel.NORMAL,
            confidence=0.7,
            blocking=False,
            detail=f"{unread} new reply(ies)",
        )


class FollowUpDuePolicy(Policy):
    """A follow-up is due for a conversation."""
    name = "follow_up_due"

    def evaluate(self, signals: dict[str, Any], reasoning: dict[str, Any]) -> PolicyResult | None:
        due = signals.get("follow_ups_due", 0)
        if due <= 0:
            return None
        return PolicyResult(
            intention_type=IntentionType.FOLLOW_UP,
            reason_code=ReasonCode.FOLLOW_UP_DUE,
            priority=PriorityLevel.NORMAL,
            confidence=0.8,
            blocking=False,
            detail=f"{due} follow-up(s) due",
        )


class MeetingPendingPolicy(Policy):
    """A meeting is scheduled or pending confirmation."""
    name = "meeting_pending"

    def evaluate(self, signals: dict[str, Any], reasoning: dict[str, Any]) -> PolicyResult | None:
        pending = signals.get("pending_meetings", 0)
        if pending <= 0:
            return None
        return PolicyResult(
            intention_type=IntentionType.NOTIFY,
            reason_code=ReasonCode.MEETING_PENDING,
            priority=PriorityLevel.NORMAL,
            confidence=0.9,
            blocking=False,
            detail=f"{pending} meeting(s) pending",
        )


class NewLeadsFoundPolicy(Policy):
    """New leads were discovered and are ready for review."""
    name = "new_leads_found"

    def evaluate(self, signals: dict[str, Any], reasoning: dict[str, Any]) -> PolicyResult | None:
        new_leads = signals.get("new_leads_count", 0)
        high_quality = signals.get("high_quality_leads", 0)
        if new_leads <= 0:
            return None
        if high_quality > 0:
            return PolicyResult(
                intention_type=IntentionType.RECOMMEND_ACTION,
                reason_code=ReasonCode.NEW_LEADS_FOUND,
                priority=PriorityLevel.HIGH,
                confidence=0.85,
                blocking=False,
                detail=f"{high_quality} high-quality lead(s) found",
            )
        return PolicyResult(
            intention_type=IntentionType.NOTIFY,
            reason_code=ReasonCode.NEW_LEADS_FOUND,
            priority=PriorityLevel.LOW,
            confidence=0.6,
            blocking=False,
            detail=f"{new_leads} new lead(s) found",
        )


class ProviderFailurePolicy(Policy):
    """A provider is failing and needs attention."""
    name = "provider_failure"

    def evaluate(self, signals: dict[str, Any], reasoning: dict[str, Any]) -> PolicyResult | None:
        failing = signals.get("failing_providers", 0)
        if failing <= 0:
            return None
        return PolicyResult(
            intention_type=IntentionType.ESCALATE,
            reason_code=ReasonCode.PROVIDER_FAILURE,
            priority=PriorityLevel.HIGH,
            confidence=0.95,
            blocking=False,
            detail=f"{failing} provider(s) failing",
        )


class ResearchCompletedPolicy(Policy):
    """Background research finished with results."""
    name = "research_completed"

    def evaluate(self, signals: dict[str, Any], reasoning: dict[str, Any]) -> PolicyResult | None:
        completed = signals.get("research_jobs_completed", 0)
        if completed <= 0:
            return None
        return PolicyResult(
            intention_type=IntentionType.NOTIFY,
            reason_code=ReasonCode.RESEARCH_COMPLETED,
            priority=PriorityLevel.LOW,
            confidence=0.9,
            blocking=False,
            detail=f"{completed} research job(s) completed",
        )


class EngagementSignalPolicy(Policy):
    """A buying signal was detected in a conversation."""
    name = "engagement_signal"

    def evaluate(self, signals: dict[str, Any], reasoning: dict[str, Any]) -> PolicyResult | None:
        signals_detected = signals.get("buying_signals_detected", 0)
        if signals_detected <= 0:
            return None
        return PolicyResult(
            intention_type=IntentionType.NOTIFY,
            reason_code=ReasonCode.SIGNAL_DETECTED,
            priority=PriorityLevel.NORMAL,
            confidence=0.75,
            blocking=False,
            detail=f"{signals_detected} buying signal(s) detected",
        )


class AutoHandleCandidatePolicy(Policy):
    """Low-risk, high-confidence action that can be auto-handled."""
    name = "auto_handle_candidate"

    def evaluate(self, signals: dict[str, Any], reasoning: dict[str, Any]) -> PolicyResult | None:
        auto_candidates = signals.get("auto_handle_candidates", 0)
        if auto_candidates <= 0:
            return None
        return PolicyResult(
            intention_type=IntentionType.AUTO_HANDLE,
            reason_code=ReasonCode.LOW_CONFIDENCE,
            priority=PriorityLevel.LOW,
            confidence=0.6,
            blocking=False,
            detail=f"{auto_candidates} auto-handle candidate(s)",
        )


class WorkspaceHealthPolicy(Policy):
    """Overall workspace health changed significantly."""
    name = "workspace_health"

    def evaluate(self, signals: dict[str, Any], reasoning: dict[str, Any]) -> PolicyResult | None:
        health = signals.get("workspace_health_score", 1.0)
        if health >= 0.8:
            return None
        return PolicyResult(
            intention_type=IntentionType.ESCALATE,
            reason_code=ReasonCode.WORKSPACE_HEALTH_CHANGED,
            priority=PriorityLevel.CRITICAL if health < 0.4 else PriorityLevel.HIGH,
            confidence=0.9,
            blocking=False,
            detail=f"Workspace health at {health:.0%}",
        )


# ── Registry of all policies ─────────────────────────────────────

DEFAULT_POLICIES: list[Policy] = [
    WorkspaceHealthPolicy(),
    CampaignReadyPolicy(),
    ProviderFailurePolicy(),
    NewReplyReceivedPolicy(),
    DraftReviewRequiredPolicy(),
    FollowUpDuePolicy(),
    MeetingPendingPolicy(),
    EngagementSignalPolicy(),
    NewLeadsFoundPolicy(),
    ResearchCompletedPolicy(),
    AutoHandleCandidatePolicy(),
]


def evaluate_policies(
    signals: dict[str, Any],
    reasoning: dict[str, Any],
    policies: list[Policy] | None = None,
) -> list[PolicyResult]:
    """Run all policies and return matched results.

    Deterministic.  No LLM calls.  Order of policies determines
    priority when multiple policies match the same signal.
    """
    policies = policies or DEFAULT_POLICIES
    results: list[PolicyResult] = []
    for policy in policies:
        try:
            result = policy.evaluate(signals, reasoning)
            if result is not None:
                results.append(result)
        except Exception:
            continue
    return results
