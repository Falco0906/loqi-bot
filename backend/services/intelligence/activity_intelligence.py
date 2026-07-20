ACTIVITY_PRIORITY_KEYWORDS: dict[str, list[str]] = {
    "high": [
        "demo", "proposal", "quote", "contract", "negotiation",
        "objection handling", "close", "decision maker",
    ],
    "medium": [
        "follow up", "check in", "touch base", "discovery",
        "qualification", "meeting",
    ],
    "low": [
        "newsletter", "notification", "alert", "spam",
        "bulk", "campaign",
    ],
}

ACTIVITY_TYPE_WEIGHTS: dict[str, int] = {
    "meeting": 100,
    "call": 80,
    "email": 60,
    "task": 40,
}


def suggest_next_activity_type(
    conversation_history: list[dict],
    opportunity_stage: str | None = None,
) -> str:
    recent_types = [a.get("type", "") for a in conversation_history[-5:]]
    if opportunity_stage in ("negotiation", "closed_won", "closed_lost"):
        return "email"

    if "meeting" not in recent_types:
        return "meeting"
    if "call" not in recent_types and len(recent_types) >= 3:
        return "call"
    return "email"


def infer_activity_priority(subject: str, body: str) -> str:
    text = f"{subject} {body}".lower()
    for priority, keywords in ACTIVITY_PRIORITY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return priority
    return "medium"


def should_log_activity(
    message_type: str,
    conversation_stage: str,
    has_crm_context: bool,
) -> bool:
    if not has_crm_context:
        return False
    if message_type in ("outbound_email", "outbound_message"):
        return True
    if conversation_stage in ("qualification", "proposal", "negotiation"):
        return True
    return False


def build_activity_summary(
    activity_type: str,
    subject: str,
    outcome: str | None = None,
) -> dict:
    return {
        "type": activity_type,
        "subject": subject,
        "outcome": outcome or "completed",
        "priority": infer_activity_priority(subject, ""),
    }
