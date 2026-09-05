from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from services.providers.capabilities import Capability, CapabilitySet
from services.providers.health import HealthCheckResult
from services.providers.interface import Provider, ProviderSetupError
from services.providers.models import MeetingStatus
from services.providers.google.calendar.mapper import CalendarMapper
from services.providers.google.oauth import GoogleOAuthFlow
from services.providers.oauth import OAuthTokenStore, TokenManager, TokenRefreshError

logger = logging.getLogger(__name__)

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


class CalendarProvider(Provider):
    """Google Calendar provider — sync, meeting detection, upcoming events.

    Uses the Calendar REST API directly.
    """

    def __init__(
        self,
        token_store: OAuthTokenStore,
        oauth_flow: GoogleOAuthFlow | None = None,
        provider_id: str = "calendar",
    ) -> None:
        self._provider_id = provider_id
        self._token_store = token_store
        self._flow = oauth_flow or GoogleOAuthFlow(
            scopes="https://www.googleapis.com/auth/calendar.events.readonly "
                   "https://www.googleapis.com/auth/calendar.readonly",
            provider_id=provider_id,
        )
        self._token_manager = TokenManager(self._flow, token_store)
        self._connected = False
        self._primary_email: str = ""
        self._mapper = CalendarMapper()

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def display_name(self) -> str:
        return f"Calendar ({self._primary_email or self._provider_id})"

    @property
    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            Capability.CALENDAR_SYNC,
            Capability.MEETING_DETECTION,
            Capability.OAUTH,
        )

    def connect(self) -> None:
        token = self._get_token()
        if not token.access_token:
            raise ProviderSetupError("Calendar: no access token available")

        resp = requests.get(
            f"{CALENDAR_API_BASE}/users/me/calendarList",
            headers=self._auth_headers(token.access_token),
            timeout=10,
        )
        if resp.status_code == 401:
            try:
                token = self._token_manager.get_valid_token(self._provider_id)
                resp = requests.get(
                    f"{CALENDAR_API_BASE}/users/me/calendarList",
                    headers=self._auth_headers(token.access_token),
                    timeout=10,
                )
            except TokenRefreshError as e:
                raise ProviderSetupError(f"Calendar: token refresh failed: {e}") from e

        if resp.status_code != 200:
            raise ProviderSetupError(
                f"Calendar: failed to connect — HTTP {resp.status_code}: {resp.text[:200]}"
            )

        items = resp.json().get("items", [])
        primary = next((c for c in items if c.get("primary")), items[0] if items else None)
        self._primary_email = (
            primary.get("id", "") if primary else ""
        )
        self._connected = True
        logger.info("CalendarProvider connected as %s", self._primary_email)

    def disconnect(self) -> None:
        self._connected = False
        self._primary_email = ""
        logger.info("CalendarProvider disconnected")

    def health(self) -> HealthCheckResult:
        if not self._connected:
            return HealthCheckResult(
                ok=False, provider_id=self._provider_id,
                status="offline", error="Not connected",
            )
        try:
            token = self._get_token()
            start = time.time()
            resp = requests.get(
                f"{CALENDAR_API_BASE}/users/me/calendarList",
                params={"maxResults": 1},
                headers=self._auth_headers(token.access_token),
                timeout=5,
            )
            elapsed = (time.time() - start) * 1000
            if resp.status_code == 200:
                return HealthCheckResult(
                    ok=True, provider_id=self._provider_id,
                    latency_ms=elapsed,
                )
            return HealthCheckResult(
                ok=False, provider_id=self._provider_id,
                latency_ms=elapsed, error=f"HTTP {resp.status_code}",
            )
        except Exception as e:
            return HealthCheckResult(
                ok=False, provider_id=self._provider_id, error=str(e),
            )

    def sync(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []

        events: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        upcoming = self._fetch_events(
            time_min=now.isoformat(),
            time_max=(now + timedelta(days=30)).isoformat(),
            order_by="startTime",
        )
        for raw in upcoming:
            meeting = self._mapper.event_to_meeting(raw, self._provider_id)
            events.append(self._build_event("MEETING_CREATED", meeting.to_dict()))

        recent = self._fetch_events(
            time_min=(now - timedelta(days=7)).isoformat(),
            time_max=now.isoformat(),
        )
        for raw in recent:
            meeting = self._mapper.event_to_meeting(raw, self._provider_id)
            if meeting.status == MeetingStatus.CANCELLED:
                events.append(self._build_event("MEETING_CANCELLED", meeting.to_dict()))
            elif meeting.end_time and meeting.end_time < now.isoformat():
                events.append(self._build_event("MEETING_COMPLETED", meeting.to_dict()))
            else:
                events.append(self._build_event("MEETING_UPDATED", meeting.to_dict()))

        return events

    def upcoming_events(self, max_results: int = 20) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        raw_events = self._fetch_events(
            time_min=now.isoformat(),
            time_max=(now + timedelta(days=30)).isoformat(),
            order_by="startTime",
            max_results=max_results,
        )
        return [
            self._mapper.event_to_meeting(e, self._provider_id).to_dict()
            for e in raw_events
        ]

    def _fetch_events(
        self,
        time_min: str,
        time_max: str,
        order_by: str = "",
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        token = self._get_token()
        params: dict[str, Any] = {
            "calendarId": "primary",
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": True,
            "maxResults": max_results,
        }
        if order_by:
            params["orderBy"] = order_by

        resp = requests.get(
            f"{CALENDAR_API_BASE}/calendars/primary/events",
            params=params,
            headers=self._auth_headers(token.access_token),
            timeout=15,
        )
        if resp.status_code == 401:
            token = self._token_manager.get_valid_token(self._provider_id)
            resp = requests.get(
                f"{CALENDAR_API_BASE}/calendars/primary/events",
                params=params,
                headers=self._auth_headers(token.access_token),
                timeout=15,
            )
        if resp.status_code != 200:
            logger.warning("Calendar: failed to fetch events — HTTP %s", resp.status_code)
            return []
        return resp.json().get("items", [])

    def _get_token(self):
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            self._token_manager.get_valid_token(self._provider_id)
        )

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _build_event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": "calendar",
            "data": data,
        }
