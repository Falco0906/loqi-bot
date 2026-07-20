"""Calendar adapter — Google Calendar operations via GoogleApiAdapter."""

from services.adapters.google.calendar.calendar_adapter import (
    CalendarAdapter,
    CALENDAR_METADATA,
    CAPABILITY_DESCRIPTORS,
    CREDENTIAL_DESCRIPTORS,
)
from services.adapters.google.calendar.models import (
    CalendarEvent,
    CalendarAttendee,
    CalendarResourceMapper,
    ListEventsRequest,
    GetEventRequest,
    CreateEventRequest,
    UpdateEventRequest,
    DeleteEventRequest,
)
from services.adapters.google.calendar.errors import (
    CalendarError,
    EventNotFoundError,
    InvalidEventDataError,
    CalendarAccessError,
    InvalidTimeRangeError,
)

__all__ = [
    "CalendarAdapter",
    "CALENDAR_METADATA",
    "CAPABILITY_DESCRIPTORS",
    "CREDENTIAL_DESCRIPTORS",
    "CalendarEvent",
    "CalendarAttendee",
    "CalendarResourceMapper",
    "ListEventsRequest",
    "GetEventRequest",
    "CreateEventRequest",
    "UpdateEventRequest",
    "DeleteEventRequest",
    "CalendarError",
    "EventNotFoundError",
    "InvalidEventDataError",
    "CalendarAccessError",
    "InvalidTimeRangeError",
]
