"""Safe, workspace-scoped campaign execution timeline projection."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from services.campaigns.service import load_campaigns
from services.persistence.launch import CampaignLaunchFailure, CampaignLaunchFailureRepository
from services.persistence.launch.communication_persistence import list_outbound_history
from services.workspace.state import load_drafts_only
from services.world_model.activity_repository import WorkspaceActivityEvent, get_activity_repository


log = logging.getLogger(__name__)

_DURABLE_TYPES = {"campaign_created", "campaign_status_changed", "draft_generated"}
_TIMELINE_TYPES = {
    "campaign_created", "campaign_status_changed", "draft_generated",
    "draft_sent", "draft_failed",
}


def _value(record: object, name: str, default: Any = "") -> Any:
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def _timestamp(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _status(value: object) -> str:
    """Normalize persisted strings and legacy enum values without exposing them."""
    return str(getattr(value, "value", value) or "").lower().removeprefix("deliverystatus.")


class CampaignTimelineService:
    """Assemble one authorized campaign's safe timeline projection.

    Events are ordered ascending by event timestamp, then source priority
    (durable activity, canonical history, launch failures), then an internal
    stable source key. Those internal keys never leave this service.
    """

    async def read(
        self,
        *,
        owner_id: str,
        workspace_id: str,
        session_token: str,
        campaign_id: str,
    ) -> dict[str, Any]:
        del session_token
        campaigns = await asyncio.to_thread(
            load_campaigns, owner_id, workspace_id=workspace_id,
        )
        if not any(str(campaign.get("id") or "") == campaign_id for campaign in campaigns):
            raise HTTPException(status_code=404, detail="Campaign not found")

        activity_events, drafts, outbound_history, launch_failures = await asyncio.gather(
            self._durable_activity(workspace_id),
            asyncio.to_thread(load_drafts_only, owner_id, workspace_id=workspace_id),
            asyncio.to_thread(list_outbound_history, workspace_id, "", 1000),
            self._launch_failures(workspace_id, campaign_id),
        )

        campaign_drafts = [
            draft for draft in drafts
            if str(draft.get("campaign_id") or "") == campaign_id
        ]
        draft_ids = {str(draft.get("id") or "") for draft in campaign_drafts}
        durable = self._durable_events(activity_events, campaign_id)
        history = self._outbound_events(outbound_history, draft_ids)
        failures = self._launch_failure_events(launch_failures, draft_ids)
        history_failures = {
            (event["_draft_id"], event["timestamp"])
            for event in history if event["type"] == "draft_failed"
        }
        failures = [
            event for event in failures
            if (event["_draft_id"], event["timestamp"]) not in history_failures
        ]

        events = durable + history + failures
        events.sort(key=lambda event: (event["timestamp"], event["_priority"], event["_key"]))
        return {
            "ok": True,
            "campaign_id": campaign_id,
            "events": [
                {key: value for key, value in event.items() if not key.startswith("_")}
                for event in events
                if event["type"] in _TIMELINE_TYPES
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
    async def _launch_failures(
        workspace_id: str, campaign_id: str,
    ) -> list[CampaignLaunchFailure]:
        try:
            return await CampaignLaunchFailureRepository().list_for_campaign(
                workspace_id=workspace_id,
                campaign_id=campaign_id,
            )
        except Exception as error:
            log.warning(
                "campaign_timeline_launch_failure_read_failed workspace_id=%s campaign_id=%s error_type=%s",
                workspace_id,
                campaign_id,
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
                "_draft_id": str(payload.get("draft_id") or ""),
            })
        return result

    @staticmethod
    def _outbound_events(history: list[object], draft_ids: set[str]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in history:
            draft_id = str(_value(item, "draft_id") or "")
            if not draft_id or draft_id not in draft_ids:
                continue
            status = _status(_value(item, "status"))
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
                "_draft_id": draft_id,
            })
        return result

    @staticmethod
    def _launch_failure_events(
        failures: list[CampaignLaunchFailure], draft_ids: set[str],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for failure in failures:
            draft_id = str(failure.draft_id or "")
            if draft_id not in draft_ids:
                continue
            timestamp = _timestamp(failure.occurred_at)
            if not timestamp:
                continue
            result.append({
                "type": "draft_failed",
                "timestamp": timestamp,
                "data": {},
                "_priority": 2,
                "_key": f"launch_failure:{failure.id}",
                "_reference": f"{failure.campaign_launch_id}:{draft_id}",
                "_revision": "",
                "_draft_id": draft_id,
            })
        return result
