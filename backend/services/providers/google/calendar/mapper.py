from __future__ import annotations

from typing import Any

from services.providers.models import ProviderMeeting, MeetingStatus


class CalendarMapper:
    """Maps raw Google Calendar API responses to normalized domain models."""

    @staticmethod
    def event_to_meeting(
        raw: dict[str, Any],
        provider_id: str = "calendar",
    ) -> ProviderMeeting:
        start = raw.get("start", {})
        end = raw.get("end", {})
        attendees_raw = raw.get("attendees", [])

        status_map = {
            "confirmed": MeetingStatus.CONFIRMED,
            "tentative": MeetingStatus.SCHEDULED,
            "cancelled": MeetingStatus.CANCELLED,
        }
        raw_status = raw.get("status", "")
        status = status_map.get(raw_status, MeetingStatus.UNKNOWN)

        return ProviderMeeting(
            title=raw.get("summary", ""),
            start_time=start.get("dateTime", start.get("date", "")),
            end_time=end.get("dateTime", end.get("date", "")),
            attendees=[a.get("email", "") for a in attendees_raw],
            status=status,
            description=raw.get("description", ""),
            location=raw.get("location", ""),
            provider_id=provider_id,
            external_id=raw.get("id", ""),
        )
