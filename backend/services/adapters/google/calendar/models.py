"""Calendar adapter models — typed request/response models
and a resource mapper for the Google Calendar v3 API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ── Request Models ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ListEventsRequest:
    calendar_id: str = "primary"
    time_min: str = ""
    time_max: str = ""
    max_results: int = 100
    query: str = ""
    show_deleted: bool = False

    def __post_init__(self) -> None:
        if self.max_results < 1 or self.max_results > 2500:
            raise ValueError("max_results must be between 1 and 2500")


@dataclass(frozen=True)
class GetEventRequest:
    event_id: str
    calendar_id: str = "primary"

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id is required")


@dataclass(frozen=True)
class CreateEventRequest:
    summary: str
    start_time: str
    end_time: str
    calendar_id: str = "primary"
    description: str = ""
    location: str = ""
    timezone: str = "UTC"
    attendees: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.summary:
            raise ValueError("summary is required")
        if not self.start_time:
            raise ValueError("start_time is required")
        if not self.end_time:
            raise ValueError("end_time is required")


@dataclass(frozen=True)
class UpdateEventRequest:
    event_id: str
    summary: str = ""
    start_time: str = ""
    end_time: str = ""
    calendar_id: str = "primary"
    description: str = ""
    location: str = ""
    timezone: str = "UTC"
    attendees: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id is required")


@dataclass(frozen=True)
class DeleteEventRequest:
    event_id: str
    calendar_id: str = "primary"

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id is required")


# ── Response Models ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    summary: str = ""
    description: str = ""
    location: str = ""
    start_time: str = ""
    end_time: str = ""
    timezone: str = "UTC"
    status: str = ""
    html_link: str = ""
    created: str = ""
    updated: str = ""
    creator_email: str = ""
    organizer_email: str = ""
    attendees: tuple[CalendarAttendee, ...] = ()
    recurrence: tuple[str, ...] = ()
    conference_data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CalendarAttendee:
    email: str = ""
    display_name: str = ""
    response_status: str = ""
    optional: bool = False


# ── Resource Mapper ─────────────────────────────────────────────────────────


class CalendarResourceMapper:
    """Converts raw Calendar v3 API JSON responses into typed domain models."""

    @staticmethod
    def to_event(raw: dict[str, Any]) -> CalendarEvent:
        start_info = raw.get("start", {})
        end_info = raw.get("end", {})

        return CalendarEvent(
            id=raw.get("id", ""),
            summary=raw.get("summary", ""),
            description=raw.get("description", ""),
            location=raw.get("location", ""),
            start_time=start_info.get("dateTime", start_info.get("date", "")),
            end_time=end_info.get("dateTime", end_info.get("date", "")),
            timezone=start_info.get("timeZone", "UTC"),
            status=raw.get("status", ""),
            html_link=raw.get("htmlLink", ""),
            created=raw.get("created", ""),
            updated=raw.get("updated", ""),
            creator_email=raw.get("creator", {}).get("email", ""),
            organizer_email=raw.get("organizer", {}).get("email", ""),
            attendees=tuple(
                CalendarResourceMapper._to_attendee(a)
                for a in raw.get("attendees", [])
            ),
            recurrence=tuple(raw.get("recurrence", [])),
            conference_data=raw.get("conferenceData", {}),
        )

    @staticmethod
    def _to_attendee(raw: dict[str, Any]) -> CalendarAttendee:
        return CalendarAttendee(
            email=raw.get("email", ""),
            display_name=raw.get("displayName", ""),
            response_status=raw.get("responseStatus", ""),
            optional=raw.get("optional", False),
        )

    @staticmethod
    def to_event_list(raw: dict[str, Any]) -> list[CalendarEvent]:
        items = raw.get("items", [])
        return [CalendarResourceMapper.to_event(item) for item in items]
