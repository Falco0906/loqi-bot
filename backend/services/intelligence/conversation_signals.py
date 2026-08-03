"""ConversationSignals — deterministic extraction of conversation-level facts.

Extracts signals from inbox/conversation data.
Today limited by available data — interfaces defined for future use.

No LLM. Pure rules.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConversationSignals:
    unanswered_threads: int
    positive_reply: bool
    objection_detected: bool
    meeting_requested: bool
    follow_up_needed: bool
    waiting_on_customer: bool

    def to_dict(self) -> dict:
        return {
            "unanswered_threads": self.unanswered_threads,
            "positive_reply": self.positive_reply,
            "objection_detected": self.objection_detected,
            "meeting_requested": self.meeting_requested,
            "follow_up_needed": self.follow_up_needed,
            "waiting_on_customer": self.waiting_on_customer,
        }


class ConversationSignalsExtractor:
    """Extracts conversation signals from workspace delta and inbox data."""

    def extract(self, delta: dict | None = None) -> ConversationSignals:
        delta = delta or {}

        new_conversations = delta.get("new_conversations", 0) or 0
        escalated = delta.get("escalated_conversations", 0) or 0
        sent = delta.get("sent_outreach", 0) or 0

        unanswered = max(new_conversations + escalated - sent, 0)

        return ConversationSignals(
            unanswered_threads=unanswered,
            positive_reply=False,
            objection_detected=False,
            meeting_requested=False,
            follow_up_needed=escalated > 0,
            waiting_on_customer=new_conversations > 0 and sent > 0,
        )
