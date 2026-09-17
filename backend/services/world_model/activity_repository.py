"""Durable, workspace-scoped activity and briefing-cursor persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


_DRAFT_GENERATED_FIELDS = {"draft_id", "campaign_id", "lead_id", "batch_job_id", "status"}
_UNSAFE_PAYLOAD_FIELDS = {
    "subject", "body", "body_preview", "lead_name", "recipient_email",
    "provider_id", "external_message_id", "thread_id", "session_token",
    "bearer", "token", "error", "prompt", "credential",
}


@dataclass(frozen=True)
class WorkspaceActivityEvent:
    """One validated, durable activity record returned in sequence order."""

    id: str
    workspace_id: str
    actor_user_id: str
    event_type: str
    payload: dict[str, Any]
    source_key: str
    sequence: int
    occurred_at: str


class WorkspaceActivityRepository:
    """Repository for the bounded durable ``draft_generated`` activity slice.

    Callers must supply already-authorized canonical workspace and user IDs.
    This repository deliberately performs no identity or session-token lookup.
    """

    events_table = "workspace_activity_events"
    cursors_table = "workspace_briefing_cursors"

    def __init__(self, client_provider: Callable[[], Any] | None = None) -> None:
        self._client_provider = client_provider

    def _client(self):
        if self._client_provider is not None:
            return self._client_provider()
        from services.platform.supabase import get_supabase_client
        return get_supabase_client()

    def append_draft_generated(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        source_key: str,
        payload: dict[str, Any],
        occurred_at: str | None = None,
    ) -> WorkspaceActivityEvent:
        """Append one idempotent, redacted draft-generation event."""
        if not workspace_id or not actor_user_id or not source_key:
            raise ValueError("Canonical workspace, actor, and source key are required")
        validated_payload = self._validate_draft_generated_payload(payload)
        client = self._client()
        if client is None:
            raise RuntimeError("Durable activity persistence is unavailable")
        result = client.rpc("append_workspace_activity_event", {
            "p_workspace_id": workspace_id,
            "p_actor_user_id": actor_user_id,
            "p_event_type": "draft_generated",
            "p_payload": validated_payload,
            "p_source_key": source_key,
            "p_occurred_at": occurred_at or datetime.now(timezone.utc).isoformat(),
        }).execute()
        rows = getattr(result, "data", None) or []
        if not rows:
            raise RuntimeError("Durable activity append was not confirmed")
        row = rows[0]
        return WorkspaceActivityEvent(
            id=str(row.get("event_id") or ""),
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            event_type="draft_generated",
            payload=validated_payload,
            source_key=source_key,
            sequence=int(row.get("event_sequence") or 0),
            occurred_at=str(row.get("occurred_at") or occurred_at or ""),
        )

    def read_cursor(self, workspace_id: str, user_id: str) -> int:
        if not workspace_id or not user_id:
            return 0
        client = self._client()
        if client is None:
            raise RuntimeError("Durable activity persistence is unavailable")
        result = (
            client.table(self.cursors_table).select("last_viewed_sequence")
            .eq("workspace_id", workspace_id).eq("user_id", user_id).limit(1).execute()
        )
        rows = getattr(result, "data", None) or []
        return int(rows[0].get("last_viewed_sequence") or 0) if rows else 0

    def read_events_after(self, workspace_id: str, after_sequence: int) -> list[WorkspaceActivityEvent]:
        if not workspace_id:
            return []
        client = self._client()
        if client is None:
            raise RuntimeError("Durable activity persistence is unavailable")
        result = (
            client.table(self.events_table).select("*").eq("workspace_id", workspace_id)
            .gt("sequence", max(0, after_sequence)).order("sequence").execute()
        )
        return [self._event(row) for row in (getattr(result, "data", None) or [])]

    def acknowledge(self, workspace_id: str, user_id: str, delivered_through_sequence: int) -> int:
        if not workspace_id or not user_id:
            raise ValueError("Canonical workspace and user are required")
        client = self._client()
        if client is None:
            raise RuntimeError("Durable activity persistence is unavailable")
        result = client.rpc("acknowledge_workspace_briefing", {
            "p_workspace_id": workspace_id,
            "p_user_id": user_id,
            "p_delivered_through_sequence": max(0, delivered_through_sequence),
        }).execute()
        rows = getattr(result, "data", None) or []
        if not rows:
            raise RuntimeError("Durable briefing acknowledgement was not confirmed")
        return int(rows[0].get("last_viewed_sequence") or 0)

    @staticmethod
    def _validate_draft_generated_payload(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Activity payload must be an object")
        keys = set(payload)
        if keys - _DRAFT_GENERATED_FIELDS or keys & _UNSAFE_PAYLOAD_FIELDS:
            raise ValueError("Activity payload contains unsupported fields")
        draft_id = str(payload.get("draft_id") or "").strip()
        batch_job_id = str(payload.get("batch_job_id") or "").strip()
        if not draft_id or not batch_job_id:
            raise ValueError("Draft activity requires draft_id and batch_job_id")
        result = {"draft_id": draft_id, "batch_job_id": batch_job_id}
        for key in ("campaign_id", "lead_id", "status"):
            value = str(payload.get(key) or "").strip()
            if value:
                result[key] = value
        return result

    @staticmethod
    def _event(row: dict[str, Any]) -> WorkspaceActivityEvent:
        return WorkspaceActivityEvent(
            id=str(row.get("id") or ""),
            workspace_id=str(row.get("workspace_id") or ""),
            actor_user_id=str(row.get("actor_user_id") or ""),
            event_type=str(row.get("event_type") or ""),
            payload=dict(row.get("payload") or {}),
            source_key=str(row.get("source_key") or ""),
            sequence=int(row.get("sequence") or 0),
            occurred_at=str(row.get("occurred_at") or ""),
        )


def get_activity_repository() -> WorkspaceActivityRepository:
    """Return the application durable activity repository."""
    return WorkspaceActivityRepository()
