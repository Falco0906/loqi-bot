"""SignalFactory — builds all intelligence signals from raw snapshot + delta.

Single entry point for the reasoning pipeline to obtain structured signals.
"""

from dataclasses import dataclass, field
from typing import Any

from services.intelligence.campaign_signals import (
    CampaignSignals,
    CampaignSignalsExtractor,
)
from services.intelligence.conversation_signals import (
    ConversationSignals,
    ConversationSignalsExtractor,
)
from services.intelligence.lead_signals import (
    LeadSignals,
    LeadSignalsExtractor,
)
from services.intelligence.provider_signals import (
    ProviderSignals,
    ProviderSignalsExtractor,
)
from services.intelligence.workspace_signals import (
    WorkspaceSignals,
    WorkspaceSignalsExtractor,
)


class SignalFactory:
    """Builds a complete signal set from raw snapshot and delta."""

    def __init__(self) -> None:
        self.campaigns = CampaignSignalsExtractor()
        self.conversations = ConversationSignalsExtractor()
        self.leads = LeadSignalsExtractor()
        self.providers = ProviderSignalsExtractor()
        self.workspace = WorkspaceSignalsExtractor()

    def build_all(
        self,
        campaigns: list[dict],
        drafts: dict | None = None,
        delta: dict | None = None,
    ) -> tuple[
        list[CampaignSignals],
        ConversationSignals,
        list[LeadSignals],
        ProviderSignals,
        WorkspaceSignals,
    ]:
        delta = delta or {}
        drafts = drafts or {}

        campaign_signals = self.campaigns.extract_all(campaigns)
        conversation_signals = self.conversations.extract(delta)
        lead_signals = self.leads.extract_all(campaigns, delta)
        provider_signals = self.providers.extract(delta)
        workspace_signals = self.workspace.extract(campaign_signals, drafts)

        return (
            campaign_signals,
            conversation_signals,
            lead_signals,
            provider_signals,
            workspace_signals,
        )
