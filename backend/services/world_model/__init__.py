"""World Model — persistent, event-sourced representation of business state.

This module is the foundation of the RFC architecture.  It defines:

- WorkspaceEvent   — immutable event type for every mutation
- WorkspaceState   — projected state derived from the event log
- WorkspaceDelta   — what changed between two points in time
- WorldModelStore  — abstract persistence interface

Phase 1: types + in-memory store defined.
Phase 2: event publishing wired into every API endpoint.
Phase 3+: state readers migrate from legacy dicts to projected state.
"""

from services.world_model.events import EventType, WorkspaceEvent
from services.world_model.state import (
    BusinessContext,
    CampaignState,
    ContactState,
    ConversationSummary,
    DraftState,
    Goal,
    JobState,
    LeadState,
    OutcomeState,
    PipelineState,
    Preference,
    ProviderState,
    RelationshipState,
    SystemState,
    WorkspaceDelta,
    WorkspaceState,
)
from services.world_model.store import (
    InMemoryWorldModelStore,
    WorldModelStore,
)
from services.world_model.publisher import get_store, publish

__all__ = [
    # Events
    "EventType",
    "WorkspaceEvent",
    # State
    "BusinessContext",
    "CampaignState",
    "ContactState",
    "ConversationSummary",
    "DraftState",
    "Goal",
    "JobState",
    "LeadState",
    "OutcomeState",
    "PipelineState",
    "Preference",
    "ProviderState",
    "RelationshipState",
    "SystemState",
    "WorkspaceDelta",
    "WorkspaceState",
    # Store
    "InMemoryWorldModelStore",
    "WorldModelStore",
    # Publisher
    "get_store",
    "publish",
]
