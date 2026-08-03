"""ProviderSignals — deterministic extraction of provider/connection facts.

Extracts signals about connected channels and their health.

No LLM. Pure rules.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderSignals:
    connected_count: int
    new_connections: int
    has_gmail: bool
    has_telegram: bool

    def to_dict(self) -> dict:
        return {
            "connected_count": self.connected_count,
            "new_connections": self.new_connections,
            "has_gmail": self.has_gmail,
            "has_telegram": self.has_telegram,
        }


class ProviderSignalsExtractor:
    """Extracts provider connectivity signals.

    Today limited by available provider data in snapshot.
    Future: read actual provider state from World Model.
    """

    def extract(self, delta: dict | None = None) -> ProviderSignals:
        delta = delta or {}
        new_providers = delta.get("new_providers", 0) or 0

        return ProviderSignals(
            connected_count=new_providers,
            new_connections=new_providers,
            has_gmail=new_providers > 0,
            has_telegram=True,
        )
