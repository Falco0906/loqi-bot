from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class CampaignPriority:
    campaign_id: str
    name: str
    status: str
    score: float
    rank: int
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "name": self.name,
            "status": self.status,
            "score": self.score,
            "rank": self.rank,
            "reasons": self.reasons[:2],
            "label": self._label(),
        }

    def _label(self) -> str:
        if self.rank == 1:
            return "Highest priority"
        if self.rank == 2:
            return "Second priority"
        if self.rank == 3:
            return "Third priority"
        return f"Priority {self.rank}"


@dataclass
class RecommendedAction:
    title: str
    reason: str
    confidence: int
    priority: str
    link: str

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "reason": self.reason,
            "confidence": self._confidence_label(),
            "priority": self.priority,
            "link": self.link,
        }

    def _confidence_label(self) -> str:
        if self.confidence >= 85:
            return "high"
        if self.confidence >= 60:
            return "medium"
        return "low"


@dataclass
class WorkspaceHealth:
    overall_health: str
    pipeline_velocity: str
    blocked_workflows: list[str] = field(default_factory=list)
    idle_campaigns: list[str] = field(default_factory=list)
    campaigns_ready: int = 0
    campaigns_waiting: int = 0
    draft_backlog: int = 0
    searches_in_progress: int = 0

    def to_dict(self) -> dict:
        return {
            "overall_health": self.overall_health,
            "pipeline_velocity": self.pipeline_velocity,
            "blocked_workflows": self.blocked_workflows,
            "idle_campaigns": self.idle_campaigns,
            "campaigns_ready": self.campaigns_ready,
            "campaigns_waiting": self.campaigns_waiting,
            "draft_backlog": self.draft_backlog,
            "searches_in_progress": self.searches_in_progress,
        }


@dataclass
class CrossCampaignInsight:
    insight: str
    insight_type: str
    campaigns_involved: list[str] = field(default_factory=list)
    importance: str = "medium"

    def to_dict(self) -> dict:
        return {
            "insight": self.insight,
            "insight_type": self.insight_type,
            "campaigns_involved": self.campaigns_involved,
        }


@dataclass
class AttentionItem:
    campaign_id: Optional[str]
    campaign_name: Optional[str]
    title: str
    reason: str
    importance: int
    urgency: int
    blocking_impact: int
    time_waiting: str
    confidence: int
    action: str
    link: str

    def to_dict(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign_name,
            "title": self.title,
            "reason": self.reason,
            "time_waiting": self.time_waiting,
            "action": self.action,
            "link": self.link,
        }


@dataclass
class WorkflowContinuation:
    should_resume: bool
    where: str
    campaign_id: Optional[str]
    campaign_name: Optional[str]
    action: str
    link: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CurrentFocus:
    focus: str
    campaign_id: Optional[str]
    campaign_name: Optional[str]
    action_type: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorkspaceAnalysis:
    current_focus: CurrentFocus
    recommended_next_action: RecommendedAction
    campaign_priorities: list[CampaignPriority]
    workspace_health: WorkspaceHealth
    cross_campaign_insights: list[CrossCampaignInsight]
    workflow_continuation: WorkflowContinuation
    attention_items: list[AttentionItem]
    analyzed_at: str

    def to_dict(self) -> dict:
        result = asdict(self)
        result["campaign_priorities"] = [cp.to_dict() for cp in self.campaign_priorities]
        result["cross_campaign_insights"] = [ci.to_dict() for ci in self.cross_campaign_insights]
        result["attention_items"] = [ai.to_dict() for ai in self.attention_items]
        return result


def _log(msg: str) -> None:
    print(f"[workspace_reasoner] {msg}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_since(iso_str: str) -> float:
    if not iso_str:
        return float("inf")
    try:
        d = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - d).total_seconds() / 3600
    except (ValueError, TypeError):
        return float("inf")


_status_score: dict[str, float] = {
    "ready_to_send": 100,
    "draft_review": 75,
    "ready": 60,
    "generating": 50,
    "planning": 30,
    "completed": 10,
    "archived": 0,
}


class WorkspaceReasoner:
    def __init__(self, snapshot: dict):
        self.snapshot = snapshot
        self.campaigns = snapshot.get("campaigns", [])
        self.drafts = snapshot.get("drafts", {})
        self.jobs = snapshot.get("jobs", {})
        self.memory = snapshot.get("memory", {})
        self.timeline = snapshot.get("timeline", [])

    def analyze(self) -> WorkspaceAnalysis:
        now = _now()
        campaign_priorities = self._rank_campaigns()
        current_focus = self._determine_focus()
        attention_items = self._build_attention_items(campaign_priorities)
        recommended_action = self._pick_next_action(attention_items, campaign_priorities)
        health = self._compute_health(campaign_priorities)
        insights = self._cross_campaign_insights()
        continuation = self._workflow_continuation(current_focus, campaign_priorities)

        return WorkspaceAnalysis(
            current_focus=current_focus,
            recommended_next_action=recommended_action,
            campaign_priorities=campaign_priorities,
            workspace_health=health,
            cross_campaign_insights=insights,
            workflow_continuation=continuation,
            attention_items=attention_items,
            analyzed_at=now,
        )

    def _rank_campaigns(self) -> list[CampaignPriority]:
        scored = []
        for c in self.campaigns:
            reasons = []
            score = _status_score.get(c.get("status", ""), 10)
            status = c.get("status", "")

            if status == "ready_to_send":
                reasons.append("All drafts approved — ready to launch")
                score += 20
            elif status == "draft_review":
                pd = c.get("pending_drafts", 0)
                score += min(pd * 5, 25)
                if pd > 0:
                    reasons.append(f"{pd} draft{'s' if pd > 1 else ''} pending review")
            elif status == "planning":
                score += 5

            approved = c.get("approved_drafts", 0)
            if approved > 0:
                score += min(approved * 3, 15)
                reasons.append(f"{approved} draft{'s' if approved > 1 else ''} approved")

            lead_count = c.get("lead_count", 0) or 0
            if lead_count > 0:
                score += min(lead_count * 0.5, 10)

            hours_since = _hours_since(c.get("updated_at", ""))
            if hours_since < 1:
                score += 15
                reasons.append("Recently updated")
            elif hours_since < 24:
                score += 8
            elif hours_since > 168 and status not in ("completed", "archived"):
                score -= 15
                reasons.append("No activity for over a week")

            if status in ("completed", "archived"):
                score = max(score, 5)

            scored.append(CampaignPriority(
                campaign_id=c.get("id", ""),
                name=c.get("name", ""),
                status=status,
                score=round(score, 1),
                rank=0,
                reasons=reasons[:3],
            ))

        scored.sort(key=lambda x: x.score, reverse=True)
        for i, cp in enumerate(scored):
            cp.rank = i + 1

        return scored

    def _determine_focus(self) -> CurrentFocus:
        last_action = self.memory.get("last_action") or ""
        last_campaign_id = self.memory.get("last_campaign_id")
        last_campaign_name = self.memory.get("last_campaign_name")

        running_jobs = self.jobs.get("running", [])
        searches = [j for j in running_jobs if j.get("type") == "search"]
        if searches:
            return CurrentFocus(
                focus=f"Searching for leads",
                campaign_id=None,
                campaign_name=None,
                action_type="searching",
            )

        if "launch" in last_action:
            return CurrentFocus(
                focus=f"Launched {last_campaign_name or 'a campaign'}",
                campaign_id=last_campaign_id,
                campaign_name=last_campaign_name,
                action_type="launching",
            )

        if "review_draft" in last_action:
            return CurrentFocus(
                focus=f"Reviewing draft for {self.memory.get('last_draft_name', 'a lead')}",
                campaign_id=last_campaign_id,
                campaign_name=last_campaign_name,
                action_type="reviewing",
            )

        if "open_campaign" in last_action and last_campaign_name:
            return CurrentFocus(
                focus=f"Reviewing {last_campaign_name}",
                campaign_id=last_campaign_id,
                campaign_name=last_campaign_name,
                action_type="reviewing",
            )

        if "search" in last_action:
            return CurrentFocus(
                focus=f"Searching for {self.memory.get('last_search', 'leads')}",
                campaign_id=None,
                campaign_name=None,
                action_type="searching",
            )

        if self.campaigns:
            top = self.campaigns[0]
            return CurrentFocus(
                focus=f"Campaign overview: {top.get('name', 'No name')}",
                campaign_id=top.get("id"),
                campaign_name=top.get("name"),
                action_type="idle",
            )

        return CurrentFocus(
            focus="Getting started",
            campaign_id=None,
            campaign_name=None,
            action_type="idle",
        )

    def _build_attention_items(self, priorities: list[CampaignPriority]) -> list[AttentionItem]:
        items = []

        for cp in priorities:
            c = next((x for x in self.campaigns if x.get("id") == cp.campaign_id), None)
            if not c:
                continue
            status = c.get("status", "")
            pd = c.get("pending_drafts", 0)
            ad = c.get("approved_drafts", 0)
            hours_since = _hours_since(c.get("updated_at", ""))

            if status == "ready_to_send":
                items.append(AttentionItem(
                    campaign_id=cp.campaign_id,
                    campaign_name=cp.name,
                    title=f"{cp.name} is ready to launch",
                    reason="All drafts have been approved. Launching now gets your outreach in front of leads.",
                    importance=9,
                    urgency=7,
                    blocking_impact=8,
                    time_waiting=self._time_waiting_label(hours_since),
                    confidence=95,
                    action="Launch Campaign",
                    link=f"/campaigns/{cp.campaign_id}",
                ))

            elif status == "draft_review" and pd > 0:
                items.append(AttentionItem(
                    campaign_id=cp.campaign_id,
                    campaign_name=cp.name,
                    title=f"{pd} draft{'s' if pd > 1 else ''} pending in {cp.name}",
                    reason="Pending drafts cannot be sent until reviewed. Each day of delay reduces reply probability.",
                    importance=8,
                    urgency=6,
                    blocking_impact=7,
                    time_waiting=self._time_waiting_label(hours_since),
                    confidence=90,
                    action="Review Drafts",
                    link="/draft",
                ))

            elif status == "planning" and c.get("lead_count", 0) > 0 and hours_since > 48:
                items.append(AttentionItem(
                    campaign_id=cp.campaign_id,
                    campaign_name=cp.name,
                    title=f"{cp.name} has been in planning for over 2 days",
                    reason="Leads are waiting. Finalizing the strategy now enables overnight draft generation.",
                    importance=6,
                    urgency=5,
                    blocking_impact=5,
                    time_waiting=self._time_waiting_label(hours_since),
                    confidence=75,
                    action="Continue Planning",
                    link=f"/campaigns/{cp.campaign_id}",
                ))

        running_jobs = self.jobs.get("running", [])
        for j in running_jobs:
            jtype = j.get("type", "job")
            if j.get("status") == "queued":
                items.append(AttentionItem(
                    campaign_id=None,
                    campaign_name=None,
                    title=f"{jtype.replace('_', ' ').title()} is queued",
                    reason="A queued job will start processing when resources are available.",
                    importance=4,
                    urgency=3,
                    blocking_impact=2,
                    time_waiting="Just queued",
                    confidence=80,
                    action="View Jobs",
                    link="/discovery",
                ))

        items.sort(key=lambda x: (x.importance + x.urgency + x.blocking_impact), reverse=True)
        return items[:8]

    def _pick_next_action(self, attention_items: list[AttentionItem], priorities: list[CampaignPriority]) -> RecommendedAction:
        if attention_items:
            top = attention_items[0]
            return RecommendedAction(
                title=top.title,
                reason=top.reason,
                confidence=top.confidence,
                priority=self._priority_label(top.importance),
                link=top.link,
            )

        if priorities:
            top_cp = priorities[0]
            c = next((x for x in self.campaigns if x.get("id") == top_cp.campaign_id), None)
            if c and c.get("status") == "planning" and c.get("lead_count", 0) > 0:
                return RecommendedAction(
                    title=f"Continue planning {top_cp.name}",
                    reason="Planning stage has leads ready to be structured into outreach.",
                    confidence=65,
                    priority="medium",
                    link=f"/campaigns/{top_cp.campaign_id}",
                )
            if c and c.get("status") == "planning":
                return RecommendedAction(
                    title="Find leads for a new campaign",
                    reason="No campaigns have leads yet. Starting with lead discovery builds pipeline momentum.",
                    confidence=70,
                    priority="medium",
                    link="/discovery",
                )

        return RecommendedAction(
            title="Start by creating a campaign",
            reason="A campaign is the first step toward running outbound outreach.",
            confidence=90,
            priority="medium",
            link="/discovery",
        )

    def _compute_health(self, priorities: list[CampaignPriority]) -> WorkspaceHealth:
        total = len(self.campaigns)
        if total == 0:
            return WorkspaceHealth(
                overall_health="empty",
                pipeline_velocity="no_pipeline",
                campaigns_ready=0,
                campaigns_waiting=0,
                draft_backlog=0,
                searches_in_progress=0,
            )

        ready = sum(1 for c in self.campaigns if c.get("status") in ("ready", "ready_to_send"))
        draft_review = sum(1 for c in self.campaigns if c.get("status") == "draft_review")
        planning = sum(1 for c in self.campaigns if c.get("status") == "planning")
        completed = sum(1 for c in self.campaigns if c.get("status") == "completed")
        archived = sum(1 for c in self.campaigns if c.get("status") == "archived")
        running_jobs = len(self.jobs.get("running", []))
        searches = len([j for j in self.jobs.get("running", []) if j.get("type") == "search"])
        backlog = self.drafts.get("pending", 0)

        idle = [c.get("name", "") for c in self.campaigns
                if c.get("status") not in ("completed", "archived")
                and _hours_since(c.get("updated_at", "")) > 72]

        blocked = []
        if planning > 0 and sum(c.get("lead_count", 0) or 0 for c in self.campaigns if c.get("status") == "planning") == 0:
            blocked.append("Planning campaigns need leads")

        active_ratio = (ready + draft_review) / max(total - archived, 1)
        if active_ratio > 0.5:
            velocity = "strong"
            overall = "healthy"
        elif active_ratio > 0.2:
            velocity = "moderate"
            overall = "moderate"
        else:
            velocity = "slow"
            overall = "at_risk" if planning > 0 and backlog == 0 else "moderate"

        return WorkspaceHealth(
            overall_health=overall,
            pipeline_velocity=velocity,
            blocked_workflows=blocked,
            idle_campaigns=idle[:5],
            campaigns_ready=ready,
            campaigns_waiting=draft_review + planning,
            draft_backlog=backlog,
            searches_in_progress=searches,
        )

    def _cross_campaign_insights(self) -> list[CrossCampaignInsight]:
        insights = []
        active = [c for c in self.campaigns if c.get("status") not in ("completed", "archived")]

        if len(active) >= 2:
            ready = [c for c in active if c.get("status") in ("ready", "ready_to_send")]
            review = [c for c in active if c.get("status") == "draft_review" and c.get("pending_drafts", 0) > 0]

            if len(ready) >= 2:
                names = [c.get("name", "") for c in ready[:2]]
                insights.append(CrossCampaignInsight(
                    insight=f"Multiple campaigns ready to launch: {' and '.join(names)}",
                    insight_type="ready",
                    campaigns_involved=[c.get("id", "") for c in ready[:2]],
                    importance="high",
                ))

            if len(review) >= 2:
                total_pending = sum(c.get("pending_drafts", 0) for c in review)
                insights.append(CrossCampaignInsight(
                    insight=f"{total_pending} drafts across {len(review)} campaigns need review",
                    insight_type="review_backlog",
                    campaigns_involved=[c.get("id", "") for c in review[:3]],
                    importance="high",
                ))

            if len(review) == 1 and len(ready) == 0:
                review_name = review[0].get("name", "")
                for c in active:
                    if c.get("status") == "planning" and c.get("id") != review[0].get("id"):
                        insights.append(CrossCampaignInsight(
                            insight=f"{review_name} needs review while {c.get('name', 'another campaign')} is waiting in planning",
                            insight_type="pipeline_gap",
                            campaigns_involved=[review[0].get("id", ""), c.get("id", "")],
                            importance="medium",
                        ))
                        break

        idle = [c for c in active if _hours_since(c.get("updated_at", "")) > 72]
        if idle:
            names = [c.get("name", "") for c in idle[:2]]
            insights.append(CrossCampaignInsight(
                insight=f"{' and '.join(names)} ha{'s' if len(idle) == 1 else 've'} had no activity for over 3 days",
                insight_type="idle",
                campaigns_involved=[c.get("id", "") for c in idle[:2]],
                importance="medium",
            ))

        return insights

    def _workflow_continuation(self, focus: CurrentFocus, priorities: list[CampaignPriority]) -> WorkflowContinuation:
        if focus.action_type in ("reviewing", "searching", "launching", "editing"):
            if focus.campaign_id:
                c = next((x for x in self.campaigns if x.get("id") == focus.campaign_id), None)
                if c and c.get("status") not in ("completed", "archived"):
                    return WorkflowContinuation(
                        should_resume=True,
                        where=f"Continue in {focus.campaign_name or 'your campaign'}",
                        campaign_id=focus.campaign_id,
                        campaign_name=focus.campaign_name,
                        action=focus.focus,
                        link=f"/campaigns/{focus.campaign_id}",
                    )

        if priorities:
            top = priorities[0]
            c = next((x for x in self.campaigns if x.get("id") == top.campaign_id), None)
            if c and c.get("status") in ("ready", "ready_to_send"):
                return WorkflowContinuation(
                    should_resume=True,
                    where=f"Launch {top.name}",
                    campaign_id=top.campaign_id,
                    campaign_name=top.name,
                    action="Launch campaign",
                    link=f"/campaigns/{top.campaign_id}",
                )
            if c and c.get("status") == "draft_review" and c.get("pending_drafts", 0) > 0:
                return WorkflowContinuation(
                    should_resume=True,
                    where=f"Review {c.get('pending_drafts', 0)} draft{'s' if c.get('pending_drafts', 0) > 1 else ''} in {top.name}",
                    campaign_id=top.campaign_id,
                    campaign_name=top.name,
                    action="Review drafts",
                    link="/draft",
                )
            if c:
                return WorkflowContinuation(
                    should_resume=True,
                    where=f"Continue working on {top.name}",
                    campaign_id=top.campaign_id,
                    campaign_name=top.name,
                    action="Continue planning",
                    link=f"/campaigns/{top.campaign_id}",
                )

        return WorkflowContinuation(
            should_resume=False,
            where="Start a new campaign",
            campaign_id=None,
            campaign_name=None,
            action="Find leads",
            link="/discovery",
        )

    def _time_waiting_label(self, hours: float) -> str:
        if hours == float("inf"):
            return "Unknown"
        if hours < 1:
            return "Less than an hour"
        if hours < 24:
            return f"{int(hours)} hour{'s' if int(hours) > 1 else ''}"
        days = int(hours / 24)
        return f"{days} day{'s' if days > 1 else ''}"

    def _priority_label(self, importance: int) -> str:
        if importance >= 8:
            return "critical"
        if importance >= 6:
            return "high"
        if importance >= 4:
            return "medium"
        return "low"
