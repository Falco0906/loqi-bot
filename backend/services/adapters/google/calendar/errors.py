"""Calendar adapter errors — thin typed wrappers around Google API errors."""

from services.adapters.base_adapter import ExecutionAdapter
from services.adapters.google.errors import GoogleApiError


class CalendarError(GoogleApiError):
    """Base calendar adapter error."""


class EventNotFoundError(CalendarError):
    """The requested calendar event does not exist."""


class InvalidEventDataError(CalendarError):
    """The event data provided is invalid or incomplete."""


class CalendarAccessError(CalendarError):
    """Access denied to the calendar resource."""


class InvalidTimeRangeError(CalendarError):
    """The provided time range is invalid."""
