"""Deterministic evidence thresholds and pattern detection for PR6."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .models import StrategicPattern, StrategicSignal

# These are deliberately operational minimums, documented rather than tuned
# to make a demo produce cards. Below these sample sizes, no update is emitted.
MIN_CAMPAIGN_SENDS = 10
MIN_REPEATED_OCCURRENCES = 3
MIN_DISTINCT_CONVERSATIONS = 2
MIN_SEGMENT_OUTCOMES = 5
MIN_FOLLOW_UPS = 3
MIN_ANGLE_OBSERVATIONS = 5


def detect_patterns(signals: list[StrategicSignal]) -> list[StrategicPattern]:
    patterns: list[StrategicPattern] = []
    patterns.extend(_campaign_patterns(signals))
    patterns.extend(_objection_patterns(signals))
    patterns.extend(_follow_up_patterns(signals))
    patterns.extend(_segment_patterns(signals))
    patterns.extend(_messaging_patterns(signals))
    return patterns


def _campaign_patterns(signals: list[StrategicSignal]) -> list[StrategicPattern]:
    grouped: dict[str, list[StrategicSignal]] = defaultdict(list)
    for signal in signals:
        if signal.campaign_id:
            grouped[signal.campaign_id].append(signal)

    patterns: list[StrategicPattern] = []
    for campaign_id, campaign_signals in grouped.items():
        outbound = [s for s in campaign_signals if s.signal_type == "outbound_sent"]
        draft_sent = [s for s in campaign_signals if s.signal_type == "draft_sent"]
        # A sent draft normally creates an outbound conversation message. Use
        # the message as the canonical send record and only fall back to the
        # draft when no conversation message exists, avoiding double counts.
        sent = outbound or draft_sent
        replies = [s for s in campaign_signals if s.signal_type == "inbound_reply"]
        positive = [
            s for s in campaign_signals
            if s.signal_type == "reply_classified" and s.value in {"interested", "meeting_request"}
        ]
        if len(sent) < MIN_CAMPAIGN_SENDS:
            continue
        response_rate = len(replies) / len(sent)
        interested_rate = len(positive) / len(sent)
        evidence = _evidence(sent + replies + positive, limit=40)
        confidence = "high" if len(sent) >= 30 else "medium"
        if replies:
            observation = (
                f"This campaign sent {len(sent)} outbound messages and received "
                f"{len(replies)} replies ({response_rate:.0%}); "
                f"{len(positive)} were interested or meeting requests."
            )
            interpretation = "The campaign has enough observed activity to assess early response quality."
            recommendation = (
                "Review the reply classifications and the strongest message context before deciding whether "
                "to scale, refine, or continue this campaign."
            )
        else:
            observation = f"This campaign sent {len(sent)} outbound messages and received no replies."
            interpretation = "The current sample shows no observed response yet; the cause is not established."
            recommendation = "Inspect the campaign audience and messaging before increasing volume."
        patterns.append(StrategicPattern(
            pattern_key=f"campaign.performance:{campaign_id}",
            update_type="performance",
            title="Campaign response pattern",
            summary=observation,
            observation=observation,
            interpretation=interpretation,
            recommendation=recommendation,
            confidence=confidence,
            observed_at=_latest(sent + replies),
            evidence=evidence,
            structured_analysis={
                "campaign_id": campaign_id,
                "sent": len(sent),
                "replies": len(replies),
                "interested": len(positive),
                "response_rate": round(response_rate, 4),
                "interested_rate": round(interested_rate, 4),
                "sample_threshold": MIN_CAMPAIGN_SENDS,
            },
        ))
    return patterns


def _objection_patterns(signals: list[StrategicSignal]) -> list[StrategicPattern]:
    grouped: dict[str, list[StrategicSignal]] = defaultdict(list)
    for signal in signals:
        if signal.signal_type == "objection":
            grouped[str(signal.value)].append(signal)

    patterns: list[StrategicPattern] = []
    for objection, matches in grouped.items():
        conversations = {s.conversation_id for s in matches if s.conversation_id}
        if len(matches) < MIN_REPEATED_OCCURRENCES or len(conversations) < MIN_DISTINCT_CONVERSATIONS:
            continue
        observation = (
            f"The {objection} concern appeared {len(matches)} times across "
            f"{len(conversations)} conversations."
        )
        patterns.append(StrategicPattern(
            pattern_key=f"objection.recurring:{objection}",
            update_type="objection",
            title=f"Recurring {objection} concern",
            summary=observation,
            observation=observation,
            interpretation=f"{objection.capitalize()} is recurring in the observed conversation sample.",
            recommendation=f"Consider addressing {objection} concerns earlier, without assuming the concern applies to every prospect.",
            confidence="medium" if len(matches) < 6 else "high",
            observed_at=_latest(matches),
            evidence=_evidence(matches, limit=30),
            structured_analysis={
                "objection": objection,
                "occurrences": len(matches),
                "distinct_conversations": len(conversations),
                "occurrence_threshold": MIN_REPEATED_OCCURRENCES,
            },
        ))
    return patterns


def _follow_up_patterns(signals: list[StrategicSignal]) -> list[StrategicPattern]:
    sent = [s for s in signals if s.signal_type == "follow_up_sent"]
    responses = [s for s in signals if s.signal_type == "follow_up_response"]
    if len(sent) < MIN_FOLLOW_UPS:
        return []
    response_rate = len(responses) / len(sent)
    observation = (
        f"{len(sent)} follow-ups were sent and {len(responses)} were followed by an inbound response "
        f"({response_rate:.0%})."
    )
    return [StrategicPattern(
        pattern_key="follow_up.response_pattern",
        update_type="follow_up",
        title="Follow-up response pattern",
        summary=observation,
        observation=observation,
        interpretation="The sample is large enough to observe whether follow-ups are producing additional conversations.",
        recommendation="Use the response examples to decide whether the follow-up timing and message should be refined.",
        confidence="medium" if len(sent) < 8 else "high",
        observed_at=_latest(sent + responses),
        evidence=_evidence(sent + responses, limit=40),
        structured_analysis={
            "follow_ups_sent": len(sent),
            "follow_up_responses": len(responses),
            "response_rate": round(response_rate, 4),
            "sample_threshold": MIN_FOLLOW_UPS,
        },
    )]


def _segment_patterns(signals: list[StrategicSignal]) -> list[StrategicPattern]:
    grouped: dict[str, list[StrategicSignal]] = defaultdict(list)
    for signal in signals:
        if signal.signal_type == "segment_outcome":
            grouped[str(signal.value)].append(signal)

    patterns: list[StrategicPattern] = []
    for segment, matches in grouped.items():
        if len(matches) < MIN_SEGMENT_OUTCOMES:
            continue
        positive = sum(1 for signal in matches if (signal.metadata or {}).get("positive"))
        positive_rate = positive / len(matches)
        if positive == 0 and len(matches) < MIN_SEGMENT_OUTCOMES * 2:
            continue
        observation = (
            f"{segment} produced {positive} positive outcomes across {len(matches)} observed conversations "
            f"({positive_rate:.0%})."
        )
        patterns.append(StrategicPattern(
            pattern_key=f"segment.outcome:{segment.lower()}",
            update_type="ICP",
            title=f"Observed response by segment: {segment}",
            summary=observation,
            observation=observation,
            interpretation="This segment has enough observed outcomes to warrant comparison with other targeting evidence.",
            recommendation=f"Consider comparing {segment} with other segments before changing ICP focus.",
            confidence="medium",
            observed_at=_latest(matches),
            evidence=_evidence(matches, limit=30),
            structured_analysis={
                "segment": segment,
                "outcomes": len(matches),
                "positive": positive,
                "positive_rate": round(positive_rate, 4),
                "sample_threshold": MIN_SEGMENT_OUTCOMES,
            },
        ))
    return patterns


def _messaging_patterns(signals: list[StrategicSignal]) -> list[StrategicPattern]:
    grouped: dict[str, list[StrategicSignal]] = defaultdict(list)
    for signal in signals:
        if signal.signal_type == "messaging_angle_used":
            grouped[str(signal.value)].append(signal)

    patterns: list[StrategicPattern] = []
    for angle, matches in grouped.items():
        if len(matches) < MIN_ANGLE_OBSERVATIONS:
            continue
        positive = sum(1 for signal in matches if (signal.metadata or {}).get("positive"))
        replies = sum(1 for signal in matches if (signal.metadata or {}).get("reply_count"))
        observation = (
            f"The messaging angle '{angle}' was used across {len(matches)} observed conversations; "
            f"{replies} received replies and {positive} had positive classifications."
        )
        patterns.append(StrategicPattern(
            pattern_key=f"messaging.angle:{angle.lower()}",
            update_type="messaging",
            title="Observed messaging angle performance",
            summary=observation,
            observation=observation,
            interpretation="This is an observed association, not proof that the angle caused the outcomes.",
            recommendation="Compare this angle with other campaign evidence before standardizing or changing messaging.",
            confidence="medium",
            observed_at=_latest(matches),
            evidence=_evidence(matches, limit=30),
            structured_analysis={
                "angle": angle,
                "observations": len(matches),
                "replies": replies,
                "positive": positive,
                "sample_threshold": MIN_ANGLE_OBSERVATIONS,
            },
        ))
    return patterns


def _evidence(signals: list[StrategicSignal], limit: int) -> list[dict[str, Any]]:
    return [signal.evidence_reference() for signal in signals[:limit]]


def _latest(signals: list[StrategicSignal]) -> str:
    return max((signal.observed_at for signal in signals), default=datetime.now(timezone.utc).isoformat())
