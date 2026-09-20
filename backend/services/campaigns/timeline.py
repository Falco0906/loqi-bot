"""Safe, workspace-scoped campaign execution timeline projection.

Durable activity and canonical outbound history are preferred.  The legacy
session-keyed World Model is retained only as a redacted compatibility fallback
for event categories that do not yet have a durable source.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from services.campaigns.service import load_campaigns
from services.persistence.launch.communication_persistence import list_outbound_history
from services.workspace.state import load_drafts_only
from services.world_model import get_store as get_wm_store
from services.world_model.activity_repository import WorkspaceActivityEvent, get_activity_repository


log = logging.getLogger(__name__)

_DURABLE_TYPES = {"campaign_created", "campaign_status_changed", "draft_generated"}
_HISTORY_TYPES = {"draft_sent", "draft_failed"}


def _value(record: object, name: str, default: Any = "") -> Any:
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def _timestamp(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


class CampaignTimelineService:
    """Assemble one authorized campaign's safe timeline projection.

    Events are ordered ascending by event timestamp, then source priority
    (durable activity, canonical history, legacy fallback), then an internal
    stable source key.  Those internal keys never leave this service.
    """

    async def read(
        self,
        *,
        owner_id: str,
        workspace_id: str,
        session_token: str,
        campaign_id: str,
    ) -> dict[str, Any]:
        campaigns = await asyncio.to_thread(
            load_campaigns, owner_id, workspace_id=workspace_id,
        )
        if not any(str(campaign.get("id") or "") == campaign_id for campaign in campaigns):
            raise HTTPException(status_code=404, detail="Campaign not found")

        activity_events, drafts, outbound_history = await asyncio.gather(
            self._durable_activity(workspace_id),
            asyncio.to_thread(load_drafts_only, owner_id, workspace_id=workspace_id),
            asyncio.to_thread(list_outbound_history, workspace_id, "", 1000),
        )

        campaign_drafts = [
            draft for draft in drafts
            if str(draft.get("campaign_id") or "") == campaign_id
        ]
        draft_ids = {str(draft.get("id") or "") for draft in campaign_drafts}
        durable = self._durable_events(activity_events, campaign_id)
        history = self._outbound_events(outbound_history, draft_ids)

        covered = self._covered_events(durable, history)
        legacy = await asyncio.to_thread(
            self._legacy_fallback_events, session_token, campaign_id, covered,
        )

        events = durable + history + legacy
        events.sort(key=lambda event: (event["timestamp"], event["_priority"], event["_key"]))
        return {
            "ok": True,
            "campaign_id": campaign_id,
            "events": [
                {key: value for key, value in event.items() if not key.startswith("_")}
                for event in events
            ],
        }

    async def _durable_activity(self, workspace_id: str) -> list[WorkspaceActivityEvent]:
        try:
            return await asyncio.to_thread(
                get_activity_repository().read_events_after, workspace_id, 0,
            )
        except Exception as error:
            log.warning(
                "campaign_timeline_activity_read_failed workspace_id=%s error_type=%s",
                workspace_id,
                type(error).__name__,
            )
            return []

    @staticmethod
    def _durable_events(
        events: list[WorkspaceActivityEvent], campaign_id: str,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for event in events:
            if event.event_type not in _DURABLE_TYPES:
                continue
            payload = event.payload
            if str(payload.get("campaign_id") or "") != campaign_id:
                continue
            data = {"status": str(payload["status"])} if payload.get("status") else {}
            result.append({
                "type": event.event_type,
                "timestamp": _timestamp(event.occurred_at),
                "data": data,
                "_priority": 0,
                "_key": f"activity:{event.sequence}:{event.id}",
                "_reference": str(payload.get("draft_id") or payload.get("campaign_id") or event.source_key),
                "_revision": event.source_key,
            })
        return result

    @staticmethod
    def _outbound_events(history: list[object], draft_ids: set[str]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in history:
            draft_id = str(_value(item, "draft_id") or "")
            if not draft_id or draft_id not in draft_ids:
                continue
            status = str(_value(item, "status") or "").lower()
            event_type = "draft_failed" if status == "failed" else "draft_sent"
            if status not in {"sent", "delivered", "failed"}:
                continue
            occurred_at = _timestamp(
                _value(item, "sent_at") or _value(item, "updated_at") or _value(item, "created_at"),
            )
            if not occurred_at:
                continue
            history_id = str(_value(item, "id") or f"{draft_id}:{occurred_at}")
            result.append({
                "type": event_type,
                "timestamp": occurred_at,
                "data": {},
                "_priority": 1,
                "_key": f"history:{history_id}",
                "_reference": draft_id,
                "_revision": "",
            })
        return result

    @staticmethod
    def _covered_events(
        durable: list[dict[str, Any]], history: list[dict[str, Any]],
    ) -> dict[str, set[str]]:
        covered: dict[str, set[str]] = {}
        for event in durable + history:
            covered.setdefault(event["type"], set()).add(event["_reference"])
            if event["type"] == "campaign_status_changed":
                covered[event["type"]].add(event["_revision"])
        return covered

    @staticmethod
    def _legacy_fallback_events(
        session_token: str,
        campaign_id: str,
        covered: dict[str, set[str]],
    ) -> list[dict[str, Any]]:
        """Read only unrepresented legacy events and redact their payloads."""
        result: list[dict[str, Any]] = []
        after_sequence = 0
        store = get_wm_store()
        while True:
            batch = store.get_events(session_token, after_sequence=after_sequence, limit=100)
            if not batch:
                break
            after_sequence = batch[-1].sequence
            for event in batch:
                data = event.data if isinstance(event.data, dict) else {}
                if str(data.get("campaign_id") or "") != campaign_id:
                    continue
                event_type = event.type.value
                reference = str(data.get("draft_id") or data.get("id") or data.get("campaign_id") or "")
                revision = str(data.get("revision") or "")
                known = covered.get(event_type, set())
                revision_key = (
                    f"campaign:{campaign_id}:revision:{revision}:status_changed"
                    if event_type == "campaign_status_changed" and revision else ""
                )
                if revision_key and revision_key in known:
                    continue
                if reference and reference in known:
                    continue
                if event_type == "campaign_created" and known:
                    continue
                safe_data = {"status": str(data["status"])} if data.get("status") else {}
                result.append({
                    "type": event_type,
                    "timestamp": _timestamp(event.timestamp),
                    "data": safe_data,
                    "_priority": 2,
                    "_key": f"legacy:{event.sequence}",
                    "_reference": reference,
                    "_revision": revision,
                })
            if len(batch) < 100:
                break
        return result
