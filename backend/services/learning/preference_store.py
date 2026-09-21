"""Durable, workspace-scoped storage for typed learned preferences."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from services.learning.models import LearnedPreference, PreferenceKey, validate_preference_value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkspacePreferenceRepository:
    """Persist current typed preference state for one canonical workspace."""

    table_name = "workspace_preferences"

    def __init__(self, client_provider: Callable[[], Any] | None = None) -> None:
        self._client_provider = client_provider

    def _client(self):
        if self._client_provider is not None:
            return self._client_provider()
        from services.platform.supabase import get_supabase_client
        return get_supabase_client()

    def get_all(self, workspace_id: str) -> list[dict[str, Any]]:
        if not workspace_id:
            return []
        client = self._client()
        if client is None:
            return []
        result = (
            client.table(self.table_name)
            .select("*")
            .eq("workspace_id", workspace_id)
            .order("preference_key")
            .execute()
        )
        return [self._record(row) for row in (getattr(result, "data", None) or [])]

    def get(self, workspace_id: str, key: str) -> dict[str, Any] | None:
        if not workspace_id or not key:
            return None
        client = self._client()
        if client is None:
            return None
        result = (
            client.table(self.table_name)
            .select("*")
            .eq("workspace_id", workspace_id)
            .eq("preference_key", key)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        return self._record(rows[0]) if rows else None

    def save_if_higher(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        preference: LearnedPreference,
    ) -> dict[str, Any]:
        """Atomically persist only a strictly higher-confidence preference."""
        if not workspace_id:
            raise ValueError("Canonical workspace_id is required for learned preferences")
        key = str(preference.key or "")
        value = str(preference.value or "")
        try:
            PreferenceKey(key)
        except ValueError as error:
            raise ValueError("Unknown learned preference key") from error
        if not validate_preference_value(key, value):
            raise ValueError("Invalid learned preference value")

        client = self._client()
        if client is None:
            raise RuntimeError("Durable preference persistence is unavailable")
        now = _utc_now()
        result = client.rpc("upsert_workspace_preference_if_higher", {
            "p_workspace_id": workspace_id,
            "p_actor_user_id": actor_user_id or None,
            "p_preference_key": key,
            "p_preference_value": value,
            "p_confidence": float(preference.confidence),
            "p_source": str(preference.source or ""),
            "p_evidence_count": int(preference.evidence_count or 0),
            "p_first_observed_at": preference.first_observed or now,
            "p_last_observed_at": preference.last_observed or now,
        }).execute()
        rows = getattr(result, "data", None) or []
        if not rows:
            raise RuntimeError("Durable preference write was not confirmed")
        record = self._record(rows[0])
        record["was_updated"] = bool(rows[0].get("was_updated") or False)
        return record

    @staticmethod
    def _record(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row.get("id") or ""),
            "workspace_id": str(row.get("workspace_id") or ""),
            "key": str(row.get("preference_key") or ""),
            "value": str(row.get("preference_value") or ""),
            "confidence": float(row.get("confidence") or 0.0),
            "source": str(row.get("source") or ""),
            "evidence_count": int(row.get("evidence_count") or 0),
            "first_observed_at": row.get("first_observed_at") or "",
            "last_observed_at": row.get("last_observed_at") or "",
            "version": int(row.get("version") or 0),
            "updated_by": str(row.get("updated_by") or ""),
            "updated_at": row.get("updated_at") or "",
        }


class PreferenceStore:
    """Typed preference access backed solely by durable workspace state."""

    def __init__(
        self,
        session_id: str = "",
        *,
        workspace_id: str = "",
        actor_user_id: str = "",
        repository: WorkspacePreferenceRepository | None = None,
    ) -> None:
        # The legacy session ID is evidence-tracker input only; it is never
        # persisted or used to scope preference data.
        del session_id
        self._workspace_id = workspace_id
        self._actor_user_id = actor_user_id
        self._repository = repository or WorkspacePreferenceRepository()

    def get_all(self) -> list[dict[str, Any]]:
        return self._repository.get_all(self._workspace_id)

    def get(self, key: PreferenceKey, default: str | None = None) -> str | None:
        row = self._repository.get(self._workspace_id, key.value)
        return row["value"] if row is not None else default

    def has(self, key: PreferenceKey) -> bool:
        return self.get(key) is not None

    def save(self, pref: LearnedPreference) -> str:
        row = self._repository.save_if_higher(
            workspace_id=self._workspace_id,
            actor_user_id=self._actor_user_id,
            preference=pref,
        )
        return row["id"]
