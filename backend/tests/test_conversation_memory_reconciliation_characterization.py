"""Characterization for R23-C-5's legacy-memory durability cutover.

These tests deliberately describe the existing compatibility behavior.  They
protect the later migration from accidentally treating a caller-supplied ID as
durable Inbox identity or changing the legacy response projection.
"""

from services.conversation_intelligence.legacy_reply_projection import (
    project_legacy_reply_intelligence,
)
from services.conversation_memory import MemoryStore, memory_store
from services.conversation_models import ConversationMessage


def setup_function():
    memory_store._store.clear()


def teardown_function():
    memory_store._store.clear()


def test_legacy_memory_is_keyed_by_the_supplied_compatibility_id():
    message = ConversationMessage(text="How much does this cost?", sender="lead")

    intelligence, memory = project_legacy_reply_intelligence(
        message,
        conversation_id="compatibility-analysis-id",
    )

    assert intelligence.conversation_id == "compatibility-analysis-id"
    assert memory.conversation_id == "compatibility-analysis-id"
    assert memory_store.get("compatibility-analysis-id") is memory


def test_replaying_the_same_legacy_analysis_does_not_duplicate_memory_values():
    message = ConversationMessage(text="How much does this cost?", sender="lead")
    _, initial_memory = project_legacy_reply_intelligence(message, conversation_id="legacy-replay")

    _, replayed_memory = project_legacy_reply_intelligence(
        message,
        conversation_id="legacy-replay",
        existing_memory=initial_memory,
    )

    assert replayed_memory.buying_signals == initial_memory.buying_signals
    assert replayed_memory.key_opportunities == initial_memory.key_opportunities
    assert memory_store.get("legacy-replay").model_dump(mode="json") == replayed_memory.model_dump(mode="json")


def test_legacy_memory_has_no_restart_rehydration_source():
    project_legacy_reply_intelligence(
        ConversationMessage(text="Can we book a demo?", sender="lead"),
        conversation_id="restart-baseline",
    )

    # A new store models a new process: there is no persistence backend to
    # reload from today.  The future durable owner must change this explicitly.
    restarted_store = MemoryStore()

    assert memory_store.get("restart-baseline") is not None
    assert restarted_store.get("restart-baseline") is None
