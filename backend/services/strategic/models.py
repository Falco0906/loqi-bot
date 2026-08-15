"""Internal normalized signal and pattern models for PR6."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StrategicSignal:
    """An observed fact derived from canonical activity; not an interpretation."""

    signal_id: str
    signal_type: str
    entity_type: str
    entity_id: str
    observed_at: str
    campaign_id: str = ""
    lead_id: str = ""
    conversation_id: str = ""
    message_id: str = ""
    value: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def evidence_reference(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "source_type": self.entity_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "campaign_id": self.campaign_id,
            "lead_id": self.lead_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "observed_at": self.observed_at,
            "value": self.value,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class StrategicPattern:
    pattern_key: str
    update_type: str
    title: str
    summary: str
    observation: str
    interpretation: str
    recommendation: str
    confidence: str
    observed_at: str
    evidence: list[dict[str, Any]]
    structured_analysis: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
