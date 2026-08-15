"""Deterministic collection of strategic signals from canonical activity."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from services.conversations.conversation_store import conversation_store
from services.conversations.timeline import TimelineEventType
from services.workspace_state import load_workspace_state

from .models import StrategicSignal


def _signal_id(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return "sig_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value or "")
    return text or datetime.now(timezone.utc).isoformat()


def _signal(
    signal_type: str,
    entity_type: str,
    entity_id: str,
    observed_at: Any,
    *,
    campaign_id: str = "",
    lead_id: str = "",
    conversation_id: str = "",
    message_id: str = "",
    value: Any = None,
    metadata: dict[str, Any] | None = None,
) -> StrategicSignal:
    observed = _iso(observed_at)
    return StrategicSignal(
        signal_id=_signal_id(signal_type, entity_type, entity_id, message_id, observed, value),
        signal_type=signal_type,
        entity_type=entity_type,
        entity_id=entity_id,
        observed_at=observed,
        campaign_id=campaign_id,
        lead_id=lead_id,
        conversation_id=conversation_id,
        message_id=message_id,
        value=value,
        metadata=metadata or {},
    )


def _lead_index(campaigns: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    leads: dict[str, dict[str, Any]] = {}
    for campaign in campaigns:
        for lead in campaign.get("leads") or []:
            if isinstance(lead, dict) and lead.get("id"):
                leads[str(lead["id"])] = lead
    return leads


def collect_workspace_signals(owner_id: str) -> tuple[list[StrategicSignal], dict[str, Any]]:
    """Collect only records belonging to the owner's workspace.

    Campaigns/drafts come from the canonical workspace state. Conversations
    are filtered through workspace campaign IDs because the current
    conversation store is campaign-linked but does not itself carry a
    workspace_id.
    """
    state = load_workspace_state(owner_id, include_details=True)
    campaigns = [c for c in state.get("campaigns", []) if not c.get("deleted_at")]
    campaign_ids = {str(c.get("id")) for c in campaigns if c.get("id")}
    campaign_by_id = {str(c.get("id")): c for c in campaigns if c.get("id")}
    leads = _lead_index(campaigns)
    drafts = [d for d in state.get("drafts", []) if not d.get("deleted_at")]

    signals: list[StrategicSignal] = []
    scoped_conversations = [
        conversation for conversation in conversation_store.list_conversations(limit=10000)
        if (
            (conversation.campaign_id and conversation.campaign_id in campaign_ids)
            or (conversation.workflow_id and conversation.workflow_id in campaign_ids)
        )
    ]

    for draft in drafts:
        if draft.get("status") != "sent" or not draft.get("campaign_id"):
            continue
        campaign_id = str(draft.get("campaign_id"))
        if campaign_id not in campaign_ids:
            continue
        signals.append(_signal(
            "draft_sent", "draft", str(draft.get("id")), draft.get("sent_at") or draft.get("created_at"),
            campaign_id=campaign_id, lead_id=str(draft.get("lead_id") or ""),
            value="sent", metadata={"subject": draft.get("subject", "")},
        ))

    for conversation in scoped_conversations:
        cid = conversation.conversation_id
        campaign_id = conversation.campaign_id or conversation.workflow_id
        lead_id = conversation.lead_id
        messages = conversation_store.get_messages_for_conversation(cid, limit=10000)
        timeline = conversation_store.get_timeline(cid)
        follow_up_events = [
            event for event in timeline
            if event.event_type == TimelineEventType.FOLLOW_UP_SENT
        ]

        for message in messages:
            if message.direction == "outbound":
                signals.append(_signal(
                    "outbound_sent", "message", message.message_id, message.sent_at,
                    campaign_id=campaign_id, lead_id=lead_id, conversation_id=cid,
                    message_id=message.message_id,
                    value="sent", metadata={"subject": message.subject},
                ))
            elif message.direction == "inbound":
                category = str((message.classification or {}).get("category") or "unknown")
                signals.append(_signal(
                    "inbound_reply", "message", message.message_id, message.sent_at,
                    campaign_id=campaign_id, lead_id=lead_id, conversation_id=cid,
                    message_id=message.message_id,
                    value=category, metadata={"body_preview": message.body_preview},
                ))
                signals.append(_signal(
                    "reply_classified", "message", message.message_id, message.sent_at,
                    campaign_id=campaign_id, lead_id=lead_id, conversation_id=cid,
                    message_id=message.message_id, value=category,
                ))
                _add_objection_signals(signals, message, campaign_id, lead_id, cid)

        for event in follow_up_events:
            signals.append(_signal(
                "follow_up_sent", "timeline_event", event.event_id, event.timestamp,
                campaign_id=campaign_id, lead_id=lead_id, conversation_id=cid,
                value="sent", metadata={"title": event.title},
            ))
            for message in messages:
                if message.direction == "inbound" and message.sent_at > event.timestamp:
                    signals.append(_signal(
                        "follow_up_response", "message", message.message_id, message.sent_at,
                        campaign_id=campaign_id, lead_id=lead_id, conversation_id=cid,
                        message_id=message.message_id,
                        value=(message.classification or {}).get("category", "unknown"),
                        metadata={"follow_up_event_id": event.event_id},
                    ))

        campaign = campaign_by_id.get(campaign_id, {})
        angle = str(
            (campaign.get("strategy") or {}).get("messaging_angle")
            or (campaign.get("strategy") or {}).get("positioning")
            or ""
        ).strip()
        if angle:
            inbound_categories = [
                str((message.classification or {}).get("category") or "unknown")
                for message in messages if message.direction == "inbound"
            ]
            signals.append(_signal(
                "messaging_angle_used", "campaign", campaign_id, conversation.updated_at,
                campaign_id=campaign_id, lead_id=lead_id, conversation_id=cid,
                value=angle,
                metadata={
                    "positive": any(category in {"interested", "meeting_request"} for category in inbound_categories),
                    "reply_count": len(inbound_categories),
                },
            ))

        lead = leads.get(str(lead_id), {})
        _add_segment_signal(signals, lead, conversation, messages)

    summary = {
        "campaign_count": len(campaigns),
        "draft_count": len(drafts),
        "conversation_count": len(scoped_conversations),
        "signal_count": len(signals),
        "campaign_ids": sorted(campaign_ids),
    }
    return signals, summary


def _add_objection_signals(signals, message, campaign_id, lead_id, conversation_id):
    text = f"{message.subject} {message.body}".lower()
    keywords = {
        "implementation": ("implementation", "setup", "onboarding", "migration"),
        "integration": ("integration", "integrate", "api", "connect"),
        "pricing": ("price", "pricing", "cost", "budget", "expensive"),
    }
    for label, terms in keywords.items():
        if any(term in text for term in terms):
            signals.append(_signal(
                "objection", "message", message.message_id, message.sent_at,
                campaign_id=campaign_id, lead_id=lead_id, conversation_id=conversation_id,
                message_id=message.message_id, value=label,
            ))


def _add_segment_signal(signals, lead, conversation, messages):
    if not lead:
        return
    industry = str(lead.get("industry") or "").strip()
    title = str(lead.get("title") or "").strip()
    segment = industry or title
    if not segment:
        return
    classifications = [
        str((message.classification or {}).get("category") or "unknown")
        for message in messages if message.direction == "inbound"
    ]
    if not classifications:
        return
    positive = any(value in {"interested", "meeting_request"} for value in classifications)
    signals.append(_signal(
        "segment_outcome", "lead", str(lead.get("id") or conversation.lead_id), conversation.updated_at,
        campaign_id=conversation.campaign_id, lead_id=conversation.lead_id,
        conversation_id=conversation.conversation_id, value=segment,
        metadata={"positive": positive, "industry": industry, "title": title},
    ))
