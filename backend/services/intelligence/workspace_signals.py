"""WorkspaceSignals — deterministic extraction of workspace-wide metrics.

Pipeline velocity, bottlenecks, throughput, workload, focus, confidence.

No LLM. Pure rules.
"""

from dataclasses import dataclass, field
from typing import Any

from services.intelligence.campaign_signals import CampaignSignals


@dataclass
class WorkspaceSignals:
    pipeline_velocity: str
    bottlenecks: list[str]
    throughput: float
    workload: int
    focus_score: float
    confidence_score: float

    def to_dict(self) -> dict:
        return {
            "pipeline_velocity": self.pipeline_velocity,
            "bottlenecks": self.bottlenecks,
            "throughput": self.throughput,
            "workload": self.workload,
            "focus_score": self.focus_score,
            "confidence_score": self.confidence_score,
        }


class WorkspaceSignalsExtractor:
    """Extracts workspace-wide signals from campaign signals and drafts data."""

    def extract(
        self,
        campaign_signals: list[CampaignSignals],
        drafts: dict | None = None,
    ) -> WorkspaceSignals:
        drafts = drafts or {}
        total = len(campaign_signals)
        if total == 0:
            return WorkspaceSignals(
                pipeline_velocity="no_pipeline",
                bottlenecks=[],
                throughput=0.0,
                workload=0,
                focus_score=0.0,
                confidence_score=0.0,
            )

        ready = sum(1 for cs in campaign_signals if cs.launch_ready)
        review = sum(1 for cs in campaign_signals if cs.pipeline_stage == "draft_review")
        planning = sum(1 for cs in campaign_signals if cs.pipeline_stage == "planning")
        archived = sum(1 for cs in campaign_signals if cs.pipeline_stage == "archived")
        stalled = sum(1 for cs in campaign_signals if cs.recent_activity == "stalled")

        idle_names = [cs.name for cs in campaign_signals if cs.recent_activity == "stalled"]

        planning_no_leads = [
            cs.name for cs in campaign_signals
            if cs.pipeline_stage == "planning" and cs.lead_count == 0
        ]

        bottlenecks: list[str] = []
        if stalled > 0:
            bottlenecks.append(f"{stalled} stalled campaign{'s' if stalled > 1 else ''}")
        if planning_no_leads:
            bottlenecks.append(f"{', '.join(planning_no_leads)} need{'s' if len(planning_no_leads) == 1 else ''} leads")

        active = ready + review + planning
        active_ratio = active / max(total - archived, 1)

        if active_ratio > 0.5:
            velocity = "strong"
        elif active_ratio > 0.2:
            velocity = "moderate"
        else:
            velocity = "slow"

        throughput = round(active_ratio, 2)

        focus_score = round(1.0 / max(active, 1), 2) if active > 0 else 0.0

        confidence_score = round(
            (ready * 1.0 + review * 0.6 + planning * 0.3) / max(active, 1),
            2,
        )

        return WorkspaceSignals(
            pipeline_velocity=velocity,
            bottlenecks=bottlenecks,
            throughput=throughput,
            workload=active,
            focus_score=focus_score,
            confidence_score=confidence_score,
        )
