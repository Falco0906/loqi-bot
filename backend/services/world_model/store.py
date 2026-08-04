from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorldModelStore(ABC):
    """Abstract interface for the World Model persistence layer.

    All World Model interactions go through this interface.  Callers
    depend on the abstraction, never on a concrete implementation.
    This enables swapping between in-memory (dev/test) and Supabase
    (production) backing stores without changing calling code.
    """

    @abstractmethod
    def append_event(self, event: WorkspaceEvent) -> str:
        """Append an event to the immutable log.

        Returns the event ID (populated if one was not set).
        """
        ...

    @abstractmethod
    def get_events(
        self,
        session_id: str,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[WorkspaceEvent]:
        """Return events for a session, ordered by sequence.

        If after_sequence is provided, only events with a higher
        sequence number are returned (incremental read).
        """
        ...

    @abstractmethod
    def get_state(self, session_id: str) -> WorkspaceState:
        """Project the current state for a session by replaying events."""
        ...

    @abstractmethod
    def get_delta(
        self,
        session_id: str,
        since: str | None = None,
    ) -> WorkspaceDelta:
        """Compute what changed since a given timestamp.

        If since is None, uses the last BRIEFING_VIEWED event as
        the boundary.  If no briefing has been viewed, returns
        the full state as a delta.
        """
        ...

    @abstractmethod
    def compute_delta(
        self,
        session_id: str,
        after_sequence: int = 0,
    ) -> WorkspaceDelta:
        """Compute what changed since a given event sequence number.

        Uses the monotonic event sequence rather than wall-clock time
        for reliable ordering.  If ``after_sequence`` is 0 (default),
        returns the full state projection as a delta — this is the
        first-visit case.

        Delta computation is deterministic: same events, same sequence
        boundary → same delta.  No LLM calls.
        """
        ...

    @abstractmethod
    def record_acknowledgement(self, session_id: str) -> tuple[str, int]:
        """Record that the user has seen the current state.

        Emits a BRIEFING_VIEWED event and records the current
        ``last_viewed_at`` and ``last_viewed_sequence`` for this session.

        Returns ``(last_viewed_at_iso, last_viewed_sequence)``.
        """
        ...

    @abstractmethod
    def get_last_sequence(self, session_id: str) -> int:
        """Return the highest sequence number for a session.

        Returns 0 if no events exist.
        """
        ...

    @abstractmethod
    def clear_session(self, session_id: str) -> None:
        """Remove all events for a session (testing helper)."""
        ...


@dataclass
class _SessionStore:
    """Internal container for one session's in-memory data."""

    events: list[WorkspaceEvent] = field(default_factory=list)
    next_sequence: int = 1


class InMemoryWorldModelStore(WorldModelStore):
    """Thread-safe in-memory World Model store.

    Backed by Python dicts.  State is lost on process restart.
    Intended for development and testing.  In production the
    SupabaseWorldModelStore (Phase 3+) replaces this.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionStore] = {}
        self._state_cache: dict[str, WorkspaceState] = {}
        self._lock = threading.Lock()

    # ── Event writing ──

    def append_event(self, event: WorkspaceEvent) -> str:
        with self._lock:
            store = self._sessions.setdefault(
                event.session_id, _SessionStore()
            )
            event.sequence = store.next_sequence
            store.next_sequence += 1
            store.events.append(event)
            self._state_cache.pop(event.session_id, None)
        return event.id

    # ── Event reading ──

    def get_events(
        self,
        session_id: str,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[WorkspaceEvent]:
        with self._lock:
            store = self._sessions.get(session_id)
            if store is None:
                return []
            return [
                e for e in store.events
                if e.sequence > after_sequence
            ][-limit:]

    def get_last_sequence(self, session_id: str) -> int:
        with self._lock:
            store = self._sessions.get(session_id)
            if store is None:
                return 0
            return store.next_sequence - 1

    # ── State projection ──

    def get_state(self, session_id: str) -> WorkspaceState:
        with self._lock:
            cached = self._state_cache.get(session_id)
            if cached is not None:
                return cached

            store = self._sessions.get(session_id)
            if store is None:
                state = WorkspaceState(session_id=session_id)
                self._state_cache[session_id] = state
                return state

            state = self._project(store.events)
            state.projected_at = _utc_now()
            self._state_cache[session_id] = state
            return state

    def _project(self, events: list[WorkspaceEvent]) -> WorkspaceState:
        """Replay events in order to derive current state.

        This is intentionally stateless (pure function of events).
        The event log is the source of truth.
        """
        state = WorkspaceState()

        for event in events:
            if not state.session_id:
                state.session_id = event.session_id

            if event.type == EventType.CAMPAIGN_CREATED:
                state.pipeline.campaigns.append(CampaignState(
                    id=event.data.get("id", ""),
                    name=event.data.get("name", ""),
                    status=event.data.get("status", "planning"),
                    lead_count=event.data.get("lead_count", 0),
                    created_at=_utc_now(),
                    updated_at=_utc_now(),
                ))

            elif event.type == EventType.CAMPAIGN_STATUS_CHANGED:
                cid = event.data.get("campaign_id", "")
                new_status = event.data.get("status", "")
                for c in state.pipeline.campaigns:
                    if c.id == cid:
                        c.status = new_status
                        c.updated_at = _utc_now()
                        break

            elif event.type == EventType.CAMPAIGN_UPDATED:
                cid = event.data.get("campaign_id", "")
                for c in state.pipeline.campaigns:
                    if c.id == cid:
                        if "name" in event.data:
                            c.name = event.data["name"]
                        if "lead_count" in event.data:
                            c.lead_count = event.data["lead_count"]
                        c.updated_at = _utc_now()
                        break

            elif event.type == EventType.LEAD_DISCOVERED:
                state.pipeline.leads.append(LeadState(
                    id=event.data.get("id", ""),
                    name=event.data.get("name", ""),
                    company=event.data.get("company", ""),
                    title=event.data.get("title", ""),
                    email=event.data.get("email", ""),
                    campaign_id=event.data.get("campaign_id", ""),
                ))

            elif event.type == EventType.LEAD_SELECTED:
                lid = event.data.get("lead_id", "")
                for lead in state.pipeline.leads:
                    if lead.id == lid:
                        lead.status = "selected"
                        break

            elif event.type == EventType.DRAFT_GENERATED:
                state.pipeline.drafts.append(DraftState(
                    id=event.data.get("id", ""),
                    campaign_id=event.data.get("campaign_id", ""),
                    lead_id=event.data.get("lead_id", ""),
                    subject=event.data.get("subject", ""),
                    body_preview=event.data.get("body_preview", ""),
                    status="pending",
                    created_at=_utc_now(),
                ))

            elif event.type == EventType.DRAFT_APPROVED:
                did = event.data.get("draft_id", "")
                for d in state.pipeline.drafts:
                    if d.id == did:
                        d.status = "approved"
                        break

            elif event.type == EventType.DRAFT_REJECTED:
                did = event.data.get("draft_id", "")
                for d in state.pipeline.drafts:
                    if d.id == did:
                        d.status = "rejected"
                        break

            elif event.type == EventType.DRAFT_UPDATED:
                did = event.data.get("draft_id", "")
                for d in state.pipeline.drafts:
                    if d.id == did:
                        new_status = event.data.get("status", "")
                        if new_status:
                            d.status = new_status
                        break

            elif event.type == EventType.DRAFT_SCHEDULED:
                did = event.data.get("draft_id", "")
                for d in state.pipeline.drafts:
                    if d.id == did:
                        d.status = "scheduled"
                        break

            elif event.type == EventType.DRAFT_SENT:
                did = event.data.get("draft_id", "")
                for d in state.pipeline.drafts:
                    if d.id == did:
                        d.status = "sent"
                        break

            elif event.type == EventType.PREFERENCE_LEARNED:
                state.business_context.preferences.append(Preference(
                    key=event.data.get("key", ""),
                    value=event.data.get("value", ""),
                    confidence=event.data.get("confidence", 0.5),
                    source=event.data.get("source", ""),
                ))

            elif event.type == EventType.ICP_UPDATED:
                state.business_context.icp = event.data.get("icp", "")

            elif event.type == EventType.GOAL_SET:
                state.business_context.goals.append(Goal(
                    description=event.data.get("description", ""),
                ))

            elif event.type == EventType.MESSAGE_RECEIVED:
                conv_id = event.data.get("conversation_id", "")
                existing = next(
                    (c for c in state.relationships.conversations if c.id == conv_id),
                    None,
                )
                if existing:
                    existing.message_count += 1
                    existing.last_message_at = _utc_now()
                else:
                    state.relationships.conversations.append(ConversationSummary(
                        id=conv_id,
                        external_thread_id=event.data.get("thread_id", ""),
                        contact_name=event.data.get("from_name", ""),
                        subject=event.data.get("subject", ""),
                        last_message_at=_utc_now(),
                        message_count=1,
                    ))

            elif event.type == EventType.CONVERSATION_ESCALATED:
                conv_id = event.data.get("conversation_id", "")
                for c in state.relationships.conversations:
                    if c.id == conv_id:
                        c.needs_attention = True
                        c.summary = event.data.get("summary", c.summary)
                        break

            elif event.type == EventType.PROVIDER_CONNECTED:
                state.system.providers.append(ProviderState(
                    id=event.data.get("provider_id", ""),
                    provider_type=event.data.get("provider_type", ""),
                    status="connected",
                    email=event.data.get("email", ""),
                ))

            elif event.type == EventType.PROVIDER_DISCONNECTED:
                pid = event.data.get("provider_id", "")
                for p in state.system.providers:
                    if p.id == pid:
                        p.status = "disconnected"
                        break

        return state

    # ── Delta computation ──

    def get_delta(
        self,
        session_id: str,
        since: str | None = None,
    ) -> WorkspaceDelta:
        with self._lock:
            store = self._sessions.get(session_id)
            if store is None:
                return WorkspaceDelta()

            if since is None:
                # Find the last BRIEFING_VIEWED event
                cutoff = None
                for e in reversed(store.events):
                    if e.type == EventType.BRIEFING_VIEWED:
                        cutoff = e.timestamp
                        break
                if cutoff is None:
                    # No briefing ever viewed → return empty
                    return WorkspaceDelta()
            else:
                try:
                    cutoff = datetime.fromisoformat(
                        since.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    cutoff = datetime.now(timezone.utc)

            delta = WorkspaceDelta()
            for e in store.events:
                if e.timestamp <= cutoff:
                    continue
                delta.event_count += 1

                if e.type == EventType.CAMPAIGN_CREATED:
                    delta.new_campaigns.append(CampaignState(
                        id=e.data.get("id", ""),
                        name=e.data.get("name", ""),
                    ))
                elif e.type == EventType.CAMPAIGN_STATUS_CHANGED:
                    delta.changed_campaigns.append(CampaignState(
                        id=e.data.get("campaign_id", ""),
                        status=e.data.get("status", ""),
                    ))
                elif e.type == EventType.DRAFT_GENERATED:
                    delta.new_drafts.append(DraftState(
                        id=e.data.get("id", ""),
                        campaign_id=e.data.get("campaign_id", ""),
                    ))
                elif e.type == EventType.LEAD_DISCOVERED:
                    delta.new_leads.append(LeadState(
                        id=e.data.get("id", ""),
                        name=e.data.get("name", ""),
                        company=e.data.get("company", ""),
                    ))
                elif e.type == EventType.MESSAGE_RECEIVED:
                    delta.new_conversations.append(ConversationSummary(
                        id=e.data.get("conversation_id", ""),
                        contact_name=e.data.get("from_name", ""),
                        subject=e.data.get("subject", ""),
                    ))
                elif e.type == EventType.CONVERSATION_ESCALATED:
                    delta.escalated_conversations.append(ConversationSummary(
                        id=e.data.get("conversation_id", ""),
                        summary=e.data.get("summary", ""),
                    ))
                elif e.type == EventType.RESEARCH_COMPLETED:
                    delta.completed_jobs.append(JobState(
                        id=e.data.get("job_id", ""),
                        type="research",
                        status="completed",
                    ))
                elif e.type == EventType.INSIGHT_GENERATED:
                    text = e.data.get("text", "")
                    if text:
                        delta.new_insights.append(text)

            return delta

    # ── Sequence-based delta (Phase 4) ──

    def compute_delta(
        self,
        session_id: str,
        after_sequence: int = 0,
    ) -> WorkspaceDelta:
        with self._lock:
            store = self._sessions.get(session_id)
            if store is None:
                delta = WorkspaceDelta(first_visit=after_sequence == 0)
                delta.event_range = (0, 0)
                return delta

            first_seq = after_sequence + 1
            delta = WorkspaceDelta(
                first_visit=(after_sequence == 0),
                event_range=(first_seq, store.next_sequence - 1),
            )

            for e in store.events:
                if e.sequence <= after_sequence:
                    continue
                delta.event_count += 1

                if e.type == EventType.CAMPAIGN_CREATED:
                    delta.new_campaigns.append(CampaignState(
                        id=e.data.get("id", ""),
                        name=e.data.get("name", ""),
                        status=e.data.get("status", "planning"),
                        lead_count=e.data.get("lead_count", 0),
                    ))
                elif e.type == EventType.CAMPAIGN_STATUS_CHANGED:
                    delta.changed_campaigns.append(CampaignState(
                        id=e.data.get("campaign_id", ""),
                        status=e.data.get("status", ""),
                    ))
                elif e.type == EventType.DRAFT_GENERATED:
                    delta.new_drafts.append(DraftState(
                        id=e.data.get("id", ""),
                        campaign_id=e.data.get("campaign_id", ""),
                        lead_id=e.data.get("lead_id", ""),
                        subject=e.data.get("subject", ""),
                        status="pending",
                    ))
                elif e.type == EventType.DRAFT_SCHEDULED:
                    delta.scheduled_drafts.append(DraftState(
                        id=e.data.get("draft_id", ""),
                        campaign_id=e.data.get("campaign_id", ""),
                        status="scheduled",
                    ))
                elif e.type == EventType.DRAFT_SENT:
                    delta.sent_outreach.append(DraftState(
                        id=e.data.get("draft_id", ""),
                        campaign_id=e.data.get("campaign_id", ""),
                        status="sent",
                    ))
                elif e.type == EventType.LEAD_DISCOVERED:
                    delta.new_leads.append(LeadState(
                        id=e.data.get("id", ""),
                        name=e.data.get("name", ""),
                        company=e.data.get("company", ""),
                        title=e.data.get("title", ""),
                    ))
                elif e.type == EventType.MESSAGE_RECEIVED:
                    delta.new_conversations.append(ConversationSummary(
                        id=e.data.get("conversation_id", ""),
                        contact_name=e.data.get("from_name", ""),
                        subject=e.data.get("subject", ""),
                    ))
                elif e.type == EventType.CONVERSATION_ESCALATED:
                    delta.escalated_conversations.append(ConversationSummary(
                        id=e.data.get("conversation_id", ""),
                        summary=e.data.get("summary", ""),
                    ))
                elif e.type == EventType.PROVIDER_CONNECTED:
                    delta.new_providers.append(ProviderState(
                        id=e.data.get("provider_id", ""),
                        provider_type=e.data.get("provider_type", ""),
                        status="connected",
                        email=e.data.get("email", ""),
                    ))
                elif e.type == EventType.RESEARCH_COMPLETED:
                    delta.completed_jobs.append(JobState(
                        id=e.data.get("job_id", ""),
                        type="research",
                        status="completed",
                    ))
                elif e.type == EventType.PREFERENCE_LEARNED:
                    delta.learned_preferences.append(Preference(
                        key=e.data.get("key", ""),
                        value=e.data.get("value", ""),
                        confidence=e.data.get("confidence", 0.5),
                        source=e.data.get("source", ""),
                    ))
                elif e.type == EventType.INSIGHT_GENERATED:
                    text = e.data.get("text", "")
                    if text:
                        delta.new_insights.append(text)

            return delta

    def record_acknowledgement(self, session_id: str) -> tuple[str, int]:
        """Record BRIEFING_VIEWED and return (iso_timestamp, sequence)."""
        event = WorkspaceEvent(
            type=EventType.BRIEFING_VIEWED,
            session_id=session_id,
            actor="user",
            data={},
        )
        eid = self.append_event(event)

        with self._lock:
            store = self._sessions.get(session_id)
            seq = store.next_sequence - 1 if store else 0
        ts = event.timestamp.isoformat()
        return ts, seq

    # ── Testing helpers ──

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
            self._state_cache.pop(session_id, None)

    def clear_all(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._state_cache.clear()
