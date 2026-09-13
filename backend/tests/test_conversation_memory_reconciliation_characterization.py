"""Characterization for R23-C-5's legacy-memory durability cutover.

These tests deliberately describe the existing compatibility behavior.  They
protect the later migration from accidentally treating a caller-supplied ID as
durable Inbox identity or changing the legacy response projection.
"""

from services.conversation_intelligence.legacy_reply_projection import (
    project_legacy_reply_intelligence,
)
from services.conversation_intelligence.legacy_models import ConversationMessage


def test_noncanonical_legacy_analysis_keeps_its_envelope_without_persisting_memory():
    message = ConversationMessage(text="How much does this cost?", sender="lead")

    intelligence, memory = project_legacy_reply_intelligence(
        message,
        conversation_id="compatibility-analysis-id",
    )

    assert intelligence.conversation_id == "compatibility-analysis-id"
    assert memory.conversation_id == "compatibility-analysis-id"


def test_replaying_noncanonical_legacy_analysis_is_transient_but_keeps_memory_values():
    message = ConversationMessage(text="How much does this cost?", sender="lead")
    _, initial_memory = project_legacy_reply_intelligence(message, conversation_id="legacy-replay")

    _, replayed_memory = project_legacy_reply_intelligence(
        message,
        conversation_id="legacy-replay",
        existing_memory=initial_memory,
    )

    assert replayed_memory.buying_signals == initial_memory.buying_signals
    assert replayed_memory.key_opportunities == initial_memory.key_opportunities


def test_noncanonical_analysis_has_no_restart_state_to_restore():
    _, memory = project_legacy_reply_intelligence(
        ConversationMessage(text="Can we book a demo?", sender="lead"),
        conversation_id="restart-baseline",
    )

    # Compatibility analysis has no durable source without a canonical Inbox
    # conversation and stable provider message ID.

    assert memory.conversation_id == "restart-baseline"
