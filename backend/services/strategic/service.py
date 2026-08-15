"""Strategic Intelligence refresh, persistence, and owner-scoped reads."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from services.persistence.launch import AuditLogRepository, StrategicUpdate, StrategicUpdateRepository

from .collector import collect_workspace_signals
from .models import StrategicPattern
from .patterns import detect_patterns


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def strategic_update_to_dict(update: StrategicUpdate) -> dict[str, Any]:
    return {
        "id": update.id,
        "workspace_id": update.workspace_id,
        "pattern_key": update.pattern_key,
        "title": update.title,
        "summary": update.summary,
        "update_type": update.update_type,
        "status": update.status,
        "confidence": update.confidence,
        "observed_at": update.observed_at.isoformat(),
        "observation": update.observation,
        "interpretation": update.interpretation,
        "recommendation": update.recommendation,
        "structured_analysis": update.structured_analysis,
        "evidence": update.evidence,
        "metadata": update.metadata,
        "created_at": update.created_at.isoformat(),
        "updated_at": update.updated_at.isoformat(),
        "archived_at": update.archived_at.isoformat() if update.archived_at else None,
    }


class StrategicIntelligenceService:
    """Thin layer over canonical workspace activity and Strategic Updates."""

    async def refresh(self, owner_id: str) -> dict[str, Any]:
        workspace_id = await self._workspace_for_owner(owner_id)
        if not workspace_id:
            return self._empty_refresh()

        signals, activity_summary = await asyncio.to_thread(
            collect_workspace_signals, owner_id,
        )
        patterns = detect_patterns(signals)
        repo = StrategicUpdateRepository()
        created = 0
        refreshed = 0
        updates: list[dict[str, Any]] = []
        for pattern in patterns:
            existing = await repo.find_by_pattern_key(workspace_id, pattern.pattern_key)
            if existing is not None and existing.deleted_at is not None:
                existing = None
            if existing is None:
                update = self._new_update(workspace_id, pattern)
                await repo.save(update)
                await self._audit(owner_id, workspace_id, "strategic_update.created", update)
                created += 1
            else:
                before = strategic_update_to_dict(existing)
                self._apply_pattern(existing, pattern)
                await repo.save(existing)
                await self._audit(
                    owner_id, workspace_id, "strategic_update.refreshed", existing,
                    before=before,
                )
                update = existing
                refreshed += 1
            updates.append(strategic_update_to_dict(update))

        all_updates = await self._list_for_workspace(workspace_id)
        return {
            "ok": True,
            "updates": all_updates,
            "refreshed_updates": refreshed,
            "new_updates": created,
            "patterns_found": len(patterns),
            "last_analyzed": datetime.now(timezone.utc).isoformat(),
            "activity_summary": activity_summary,
        }

    async def list_updates(
        self,
        owner_id: str,
        *,
        update_type: str | None = None,
        confidence: str | None = None,
        query: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        workspace_id = await self._workspace_for_owner(owner_id)
        if not workspace_id:
            return []
        updates = await self._list_for_workspace(workspace_id, include_archived=include_archived)
        query = (query or "").strip().lower()
        return [
            update for update in updates
            if (not update_type or update["update_type"].lower() == update_type.lower())
            and (not confidence or update["confidence"].lower() == confidence.lower())
            and (not query or query in " ".join([
                update["title"], update["summary"], update["observation"],
                update["interpretation"], update["recommendation"],
            ]).lower())
        ]

    async def get_update(self, owner_id: str, update_id: str) -> dict[str, Any] | None:
        workspace_id = await self._workspace_for_owner(owner_id)
        if not workspace_id:
            return None
        update = await StrategicUpdateRepository().get(update_id)
        if update is None or update.workspace_id != workspace_id or update.deleted_at is not None:
            return None
        return strategic_update_to_dict(update)

    async def archive_update(self, owner_id: str, update_id: str) -> dict[str, Any] | None:
        workspace_id = await self._workspace_for_owner(owner_id)
        if not workspace_id:
            return None
        repo = StrategicUpdateRepository()
        update = await repo.get(update_id)
        if update is None or update.workspace_id != workspace_id or update.deleted_at is not None:
            return None
        now = datetime.now(timezone.utc)
        before = strategic_update_to_dict(update)
        update.status = "archived"
        update.archived_at = now
        update.deleted_at = now
        update.updated_at = now
        await repo.save(update)
        await self._audit(owner_id, workspace_id, "strategic_update.archived", update, before=before)
        return strategic_update_to_dict(update)

    async def _workspace_for_owner(self, owner_id: str) -> str | None:
        if not owner_id:
            return None
        from services.workspace_state import _async_workspace
        return await _async_workspace(owner_id)

    async def _list_for_workspace(
        self, workspace_id: str, *, include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        updates = await StrategicUpdateRepository().list_for_workspace(workspace_id)
        return [
            strategic_update_to_dict(update)
            for update in updates
            if include_archived or update.deleted_at is None
        ]

    @staticmethod
    def _new_update(workspace_id: str, pattern: StrategicPattern) -> StrategicUpdate:
        return StrategicUpdate(
            workspace_id=workspace_id,
            pattern_key=pattern.pattern_key,
            title=pattern.title,
            summary=pattern.summary,
            update_type=pattern.update_type.lower(),
            confidence=pattern.confidence,
            observed_at=_parse_datetime(pattern.observed_at),
            observation=pattern.observation,
            interpretation=pattern.interpretation,
            recommendation=pattern.recommendation,
            structured_analysis=pattern.structured_analysis,
            evidence=pattern.evidence,
            metadata=pattern.metadata,
        )

    @staticmethod
    def _apply_pattern(update: StrategicUpdate, pattern: StrategicPattern) -> None:
        update.title = pattern.title
        update.summary = pattern.summary
        update.update_type = pattern.update_type.lower()
        update.status = "active"
        update.confidence = pattern.confidence
        update.observed_at = _parse_datetime(pattern.observed_at)
        update.observation = pattern.observation
        update.interpretation = pattern.interpretation
        update.recommendation = pattern.recommendation
        update.structured_analysis = pattern.structured_analysis
        update.evidence = pattern.evidence
        update.metadata = pattern.metadata
        update.updated_at = datetime.now(timezone.utc)

    async def _audit(
        self,
        owner_id: str,
        workspace_id: str,
        action: str,
        update: StrategicUpdate,
        *,
        before: dict[str, Any] | None = None,
    ) -> None:
        try:
            await AuditLogRepository().record(
                workspace_id=workspace_id,
                user_id=owner_id,
                action=action,
                entity_type="strategic_update",
                entity_id=update.id,
                before=before,
                after=strategic_update_to_dict(update),
                metadata={"pattern_key": update.pattern_key},
            )
        except Exception:
            # Audit failure must not discard the primary intelligence result.
            pass

    @staticmethod
    def _empty_refresh() -> dict[str, Any]:
        return {
            "ok": True,
            "updates": [],
            "refreshed_updates": 0,
            "new_updates": 0,
            "patterns_found": 0,
            "last_analyzed": datetime.now(timezone.utc).isoformat(),
            "activity_summary": {
                "campaign_count": 0,
                "draft_count": 0,
                "conversation_count": 0,
                "signal_count": 0,
                "campaign_ids": [],
            },
        }
