"""Durable, authorized storage for the legacy conversation-memory projection.

This is deliberately separate from Inbox snapshots: intelligence updates have
their own idempotency and compare-and-swap lifecycle. The active legacy
This boundary is the canonical owner after R23-C-5. Raw compatibility
analysis without canonical scope remains transient by design.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Any

from services.conversation_intelligence.legacy_models import (
    BuyingSignal,
    ConversationMemory,
    ConversationMessage,
    ConversationStage,
    IntentPrediction,
)
from services.conversations.conversation_store import (
    conversation_in_workspace,
    conversation_owned_by,
    conversation_store,
)
from services.persistence import json_file
from services.platform.supabase import get_supabase_client


_CATEGORY = "conversation_intelligence_memories"
_MAX_SOURCE_MESSAGE_IDS = 200


def _local_fallback_allowed() -> bool:
    environment = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "development").strip().lower()
    return environment != "production" or os.getenv("LOQI_ALLOW_LOCAL_CONVERSATION_SNAPSHOTS", "").lower() in {"1", "true", "yes"}


def _default_state_file() -> str:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, ".conversation_intelligence_memories.json")


STATE_FILE = (
    os.getenv("CONVERSATION_INTELLIGENCE_MEMORY_STATE_FILE", "")
    or _default_state_file()
)


class ConversationMemoryAccessError(Exception):
    """The requested canonical Inbox conversation is unavailable to the caller."""


class ConversationMemoryVersionConflict(Exception):
    """A newer durable memory write won the compare-and-swap race."""


@dataclass(frozen=True)
class LegacyConversationMemoryRecord:
    conversation_id: str
    owner_id: str
    workspace_id: str
    memory: ConversationMemory
    source_message_ids: tuple[str, ...]
    version: int
    updated_at: str


def _extract_questions(text: str) -> list[str]:
    import re

    return [line.strip() for line in re.split(r"[.!?\n]", text) if "?" in line and len(line.strip()) > 5][:5]


def _extract_pain_points(text: str) -> list[str]:
    indicators = (
        "struggling with", "challenge is", "difficult to", "problem with",
        "issue we have", "frustrating", "hard to", "not working", "broken",
        "inefficient", "too slow", "too many", "wasting", "not enough", "can't", "cannot",
    )
    lowered = text.lower()
    return [
        text[max(0, lowered.index(indicator) - 20):min(len(text), lowered.index(indicator) + len(indicator) + 60)].strip()
        for indicator in indicators if indicator in lowered
    ][:3]


def build_legacy_memory(
    *,
    conversation_id: str,
    message: ConversationMessage,
    intents: list[IntentPrediction],
    buying_signals: list[BuyingSignal],
    stage: ConversationStage,
    stage_reasoning: str,
    followup_action: str = "",
    existing_memory: ConversationMemory | None = None,
    decision_confidence: int = 0,
    urgency: str = "",
    top_objection: str = "",
) -> ConversationMemory:
    """Build the legacy memory projection without choosing a persistence path."""
    memory = existing_memory.model_copy(deep=True) if existing_memory else ConversationMemory(conversation_id=conversation_id)
    memory.current_stage = stage
    memory.summary = f"Message from {message.sender or 'unknown'}: {message.text[:100]}..."
    for question in _extract_questions(message.text):
        if question not in memory.open_questions:
            memory.open_questions.append(question)
    for pain in _extract_pain_points(message.text):
        if pain not in memory.pain_points:
            memory.pain_points.append(pain)
    for intent in intents:
        risks = {
            "budget_concern": "Budget concern raised by lead",
            "timing_concern": "Timing delay risk",
            "authority_concern": "Authority concerns — may need multiple stakeholders",
            "competitor_mention": "Competitor evaluation in progress",
        }
        risk = risks.get(intent.intent.value)
        if risk and risk not in memory.key_risks:
            memory.key_risks.append(risk)
    for signal in buying_signals:
        signal_name = signal.signal.replace("_", " ").title()
        if signal_name not in memory.buying_signals:
            memory.buying_signals.append(signal_name)
    if followup_action and followup_action not in memory.last_followup:
        memory.last_followup = followup_action
    signal_names = {signal.signal for signal in buying_signals}
    for name, opportunity in {
        "asked_for_pricing": "Pricing discussion",
        "requested_demo": "Demo opportunity",
        "requested_meeting": "Meeting opportunity",
    }.items():
        if name in signal_names and opportunity not in memory.key_opportunities:
            memory.key_opportunities.append(opportunity)
    if buying_signals:
        strengths = {signal.strength.value for signal in buying_signals}
        memory.urgency = "high" if strengths & {"very_strong", "strong"} else "medium" if "medium" in strengths else "low"
    memory.last_recommendation = stage_reasoning
    if top_objection:
        memory.top_objection = top_objection
    if decision_confidence:
        memory.decision_confidence = decision_confidence
    if urgency:
        memory.urgency = urgency
    return memory


def _authorized_conversation(*, conversation_id: str, owner_id: str, workspace_id: str):
    conversation = conversation_store.get_conversation(conversation_id)
    if (
        conversation is None
        or not conversation_owned_by(conversation, owner_id)
        or not conversation_in_workspace(conversation, workspace_id)
    ):
        raise ConversationMemoryAccessError("Conversation is unavailable")
    return conversation


def _record_from_row(row: dict[str, Any]) -> LegacyConversationMemoryRecord:
    memory_payload = row.get("memory") if isinstance(row.get("memory"), dict) else {}
    source_ids = row.get("processed_source_message_ids") or row.get("source_message_ids") or []
    return LegacyConversationMemoryRecord(
        conversation_id=str(row.get("conversation_id") or ""),
        owner_id=str(row.get("owner_id") or ""),
        workspace_id=str(row.get("workspace_id") or ""),
        memory=ConversationMemory.model_validate(memory_payload),
        source_message_ids=tuple(str(item) for item in source_ids if str(item)),
        version=int(row.get("version") or 0),
        updated_at=str(row.get("updated_at") or ""),
    )


def _load_local_rows() -> dict[str, dict[str, Any]]:
    data, status = json_file.read_json(STATE_FILE, category=_CATEGORY)
    if status is json_file.JsonFileStatus.ABSENT:
        return {}
    if status is not json_file.JsonFileStatus.OK or not isinstance(data, dict):
        raise RuntimeError("Conversation intelligence memory persistence is unreadable")
    rows = data.get("records") or {}
    if not isinstance(rows, dict):
        raise RuntimeError("Conversation intelligence memory persistence has invalid records")
    return rows


def _save_local_rows(rows: dict[str, dict[str, Any]]) -> None:
    current, status = json_file.read_json(STATE_FILE, category=_CATEGORY)
    if status is json_file.JsonFileStatus.OK and isinstance(current, dict):
        sequence = int(current.get("sequence") or 0) + 1
    elif status is json_file.JsonFileStatus.ABSENT:
        sequence = 1
    else:
        raise RuntimeError("Conversation intelligence memory persistence is unreadable")
    json_file.atomic_write_json(
        STATE_FILE,
        {"sequence": sequence, "records": rows},
        sequence_key="sequence",
        category=_CATEGORY,
    )


def load_legacy_memory(
    *, conversation_id: str, owner_id: str, workspace_id: str,
) -> LegacyConversationMemoryRecord | None:
    """Load a legacy-compatible memory only after canonical scope validation."""
    _authorized_conversation(
        conversation_id=conversation_id,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )
    client = get_supabase_client()
    if client is not None:
        try:
            result = client.table("conversation_intelligence_memories").select(
                "conversation_id, owner_id, workspace_id, memory, processed_source_message_ids, version, updated_at"
            ).eq("conversation_id", conversation_id).eq("owner_id", owner_id).eq(
                "workspace_id", workspace_id
            ).limit(1).execute()
            rows = getattr(result, "data", None) or []
            return _record_from_row(rows[0]) if rows else None
        except Exception:
            if not _local_fallback_allowed():
                raise
    row = _load_local_rows().get(conversation_id)
    if row is None:
        return None
    if str(row.get("owner_id") or "") != str(owner_id) or str(row.get("workspace_id") or "") != str(workspace_id):
        raise ConversationMemoryAccessError("Conversation is unavailable")
    return _record_from_row(row)


def canonical_memory_scope(conversation_id: str) -> tuple[str, str] | None:
    """Return server-derived owner/workspace for an Inbox conversation.

    This is intentionally for trusted internal providers such as Gmail sync.
    HTTP callers must use ``load_legacy_memory``/``persist_legacy_memory``
    with their authenticated owner and selected workspace.
    """
    conversation = conversation_store.get_conversation(conversation_id)
    if conversation is None:
        return None
    metadata = getattr(conversation, "metadata", {}) or {}
    owner_id = str(getattr(conversation, "owner_id", "") or "")
    workspace_id = str(metadata.get("workspace_id") or "") if isinstance(metadata, dict) else ""
    return (owner_id, workspace_id) if owner_id and workspace_id else None


def persist_legacy_memory(
    *,
    conversation_id: str,
    owner_id: str,
    workspace_id: str,
    memory: ConversationMemory,
    source_message_id: str,
    expected_version: int,
) -> LegacyConversationMemoryRecord:
    """Persist one canonical memory update with source-message idempotency."""
    _authorized_conversation(
        conversation_id=conversation_id,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )
    if not source_message_id:
        raise ValueError("source_message_id is required")
    if memory.conversation_id != conversation_id:
        raise ValueError("memory conversation_id must match canonical conversation_id")

    client = get_supabase_client()
    if client is not None:
        try:
            result = client.rpc("persist_conversation_intelligence_memory", {
                "p_conversation_id": conversation_id,
                "p_owner_id": owner_id,
                "p_workspace_id": workspace_id,
                "p_memory": memory.model_dump(mode="json"),
                "p_source_message_id": source_message_id,
                "p_expected_version": expected_version,
            }).execute()
            version = int(getattr(result, "data", 0) or 0)
            current = load_legacy_memory(
                conversation_id=conversation_id,
                owner_id=owner_id,
                workspace_id=workspace_id,
            )
            if current is None or current.version != version:
                raise RuntimeError("Conversation intelligence memory write could not be verified")
            return current
        except Exception as error:
            if not _local_fallback_allowed():
                raise ConversationMemoryVersionConflict from error

    rows = _load_local_rows()
    existing = rows.get(conversation_id)
    if existing is not None:
        if str(existing.get("owner_id") or "") != str(owner_id) or str(existing.get("workspace_id") or "") != str(workspace_id):
            raise ConversationMemoryAccessError("Conversation is unavailable")
        source_ids = [str(item) for item in existing.get("source_message_ids") or []]
        if source_message_id in source_ids:
            return _record_from_row(existing)
        if int(existing.get("version") or 0) != expected_version:
            raise ConversationMemoryVersionConflict("Conversation intelligence memory version conflict")
    elif expected_version != 0:
        raise ConversationMemoryVersionConflict("Conversation intelligence memory version conflict")
    else:
        source_ids = []

    source_ids = (source_ids + [source_message_id])[-_MAX_SOURCE_MESSAGE_IDS:]
    row = {
        "conversation_id": conversation_id,
        "owner_id": owner_id,
        "workspace_id": workspace_id,
        "memory": memory.model_dump(mode="json"),
        "source_message_ids": source_ids,
        "version": (int(existing.get("version") or 0) if existing else 0) + 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    rows[conversation_id] = row
    _save_local_rows(rows)
    return _record_from_row(row)
