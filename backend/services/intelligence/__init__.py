"""Intelligence Layer — describes reality through deterministic signals.

Architectural role (per ARCHITECTURE_RFC.md, Layer 3):

  Intelligence Layer     ← YOU ARE HERE
      ↓ signals
  Reasoning Layer
      ↓ structured data
  Narrative Engine
      ↓ natural language
  Experience Layer

Signals expose facts about raw state.
They do NOT make decisions — reasoners do.

Extractors in this package:
  - CampaignSignalsExtractor   (per-campaign: stage, stalls, drafts, leads)
  - ConversationSignalsExtractor (per-workspace: threads, replies, objections)
  - LeadSignalsExtractor        (per-campaign aggregate: icp_match, freshness)
  - ProviderSignalsExtractor    (per-workspace: connections)
  - WorkspaceSignalsExtractor   (per-workspace: velocity, bottlenecks, throughput)
"""

from services.intelligence.campaign_signals import CampaignSignals, CampaignSignalsExtractor
from services.intelligence.conversation_signals import ConversationSignals, ConversationSignalsExtractor
from services.intelligence.lead_signals import LeadSignals, LeadSignalsExtractor
from services.intelligence.provider_signals import ProviderSignals, ProviderSignalsExtractor
from services.intelligence.workspace_signals import WorkspaceSignals, WorkspaceSignalsExtractor
