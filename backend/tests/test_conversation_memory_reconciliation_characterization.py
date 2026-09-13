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


def test_noncanonical_legacy_analysis_keeps_its_envelope_without_persisting_memory():
    message = ConversationMessage(text="How much does this cost?", sender="lead")

    intelligence, memory = project_legacy_reply_intelligence(
        message,
        conversation_id="compatibility-analysis-id",
    )

    assert intelligence.conversation_id == "compatibility-analysis-id"
    assert memory.conversation_id == "compatibility-analysis-id"
    assert memory_store.get("compatibility-analysis-id") is None


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
    assert memory_store.get("legacy-replay") is None


def test_process_local_compatibility_store_is_not_used_by_new_analysis_path():
    _, memory = project_legacy_reply_intelligence(
        ConversationMessage(text="Can we book a demo?", sender="lead"),
        conversation_id="restart-baseline",
    )

    # The retired compatibility store remains process-local until C5e, but
    # projection callers no longer write it. A new process has no legacy
    # state to restore; canonical Gmail analysis writes the durable boundary.
    restarted_store = MemoryStore()

    assert memory.conversation_id == "restart-baseline"
    assert memory_store.get("restart-baseline") is None
    assert restarted_store.get("restart-baseline") is None
