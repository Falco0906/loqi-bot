"""CalendarAdapter — Google Calendar operations via the Google API Base Adapter.

Translates Calendar concepts into Google Calendar v3 REST API requests,
maps responses into typed domain models, and provides Calendar-specific
error handling.  All HTTP execution flows through ``GoogleApiAdapter`` —
no HTTP logic is duplicated.
"""

from __future__ import annotations

from typing import Any

from services.adapters.base_adapter import ExecutionAdapter
from services.adapters.adapter_context import AdapterContext
from services.adapters.models import AdapterMetadata, AdapterResult
from services.adapters.google.google_api_adapter import GoogleApiAdapter
from services.adapters.google.calendar.models import (
    CalendarResourceMapper,
    ListEventsRequest,
    GetEventRequest,
    CreateEventRequest,
    UpdateEventRequest,
    DeleteEventRequest,
    CalendarEvent,
)
from services.adapters.google.calendar.errors import (
    CalendarError,
    EventNotFoundError,
    InvalidEventDataError,
    CalendarAccessError,
    InvalidTimeRangeError,
)


CALENDAR_METADATA = AdapterMetadata(
    name="calendar",
    display_name="Google Calendar Adapter",
    version="1.0.0",
    description="Google Calendar Adapter — list, get, create, update, and "
    "delete calendar events. "
    "Built on the Google API Base Adapter.",
    author="Loqi",
    supported_operations=(
        "calendar_list_events",
        "calendar_get_event",
        "calendar_create_event",
        "calendar_update_event",
        "calendar_delete_event",
    ),
    requires_auth=True,
    supports_streaming=False,
    supports_batch=False,
    supports_retry=True,
    tags=("calendar", "google", "workspace"),
)

CAPABILITY_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": "calendar_list_events",
        "display_name": "List Events",
        "description": "List calendar events with optional time range and filters",
        "category": "calendar",
        "version": "1.0.0",
        "requires_auth": True,
    },
    {
        "name": "calendar_get_event",
        "display_name": "Get Event",
        "description": "Retrieve a single calendar event by ID",
        "category": "calendar",
        "version": "1.0.0",
        "requires_auth": True,
    },
    {
        "name": "calendar_create_event",
        "display_name": "Create Event",
        "description": "Create a new calendar event",
        "category": "calendar",
        "version": "1.0.0",
        "requires_auth": True,
    },
    {
        "name": "calendar_update_event",
        "display_name": "Update Event",
        "description": "Update an existing calendar event",
        "category": "calendar",
        "version": "1.0.0",
        "requires_auth": True,
    },
    {
        "name": "calendar_delete_event",
        "display_name": "Delete Event",
        "description": "Delete a calendar event",
        "category": "calendar",
        "version": "1.0.0",
        "requires_auth": True,
    },
]

CREDENTIAL_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": "google_oauth2",
        "display_name": "Google OAuth2",
        "description": "OAuth2 access token for Google Calendar API authentication",
        "auth_type": "oauth2",
    },
]

_CALENDAR_ID = "calendars/{calendar_id}/events"
_EVENT_RESOURCE = f"{_CALENDAR_ID}/{{event_id}}"


class CalendarAdapter(ExecutionAdapter):
    """Calendar adapter — thin domain layer on top of GoogleApiAdapter.

    Translates Calendar concepts into Google API requests, maps responses
    into typed domain models, and provides Calendar-specific error handling.
    All HTTP execution flows through ``GoogleApiAdapter``.
    """

    def __init__(
        self,
        google_adapter: GoogleApiAdapter | None = None,
    ) -> None:
        self._google = google_adapter or GoogleApiAdapter()
        self._mapper = CalendarResourceMapper()

    @property
    def metadata(self) -> AdapterMetadata:
        return CALENDAR_METADATA

    async def execute(self, context: AdapterContext) -> AdapterResult:
        action = context.action

        dispatch = {
            "calendar_list_events": self._list_events,
            "calendar_get_event": self._get_event,
            "calendar_create_event": self._create_event,
            "calendar_update_event": self._update_event,
            "calendar_delete_event": self._delete_event,
        }

        handler = dispatch.get(action)
        if handler is None:
            return AdapterResult.failure_result(
                error=f"Unknown Calendar action: {action!r}",
                metadata={"error_type": "CalendarError"},
            )

        return await handler(context)

    # ── Operation handlers ──────────────────────────────────────────────

    async def _list_events(self, context: AdapterContext) -> AdapterResult:
        req = _build_list_events_request(context.params)
        calendar_id = req.calendar_id
        resource = _CALENDAR_ID.format(calendar_id=calendar_id)

        query: dict[str, str] = {"maxResults": str(req.max_results)}
        if req.time_min:
            query["timeMin"] = req.time_min
        if req.time_max:
            query["timeMax"] = req.time_max
        if req.query:
            query["q"] = req.query
        if req.show_deleted:
            query["showDeleted"] = "true"

        gc = _google_context(
            context=context,
            service="calendar",
            resource=resource,
            query=query,
        )
        result = await self._google.execute(gc)
        return _map_list_result(result, self._mapper)

    async def _get_event(self, context: AdapterContext) -> AdapterResult:
        req = _build_get_event_request(context.params)
        resource = _EVENT_RESOURCE.format(
            calendar_id=req.calendar_id,
            event_id=req.event_id,
        )

        gc = _google_context(
            context=context,
            service="calendar",
            resource=resource,
        )
        result = await self._google.execute(gc)
        return _map_get_event_result(result, self._mapper)

    async def _create_event(self, context: AdapterContext) -> AdapterResult:
        req = _build_create_event_request(context.params)
        calendar_id = req.calendar_id
        resource = _CALENDAR_ID.format(calendar_id=calendar_id)

        body = _build_event_body(
            summary=req.summary,
            start_time=req.start_time,
            end_time=req.end_time,
            timezone=req.timezone,
            description=req.description,
            location=req.location,
            attendees=list(req.attendees),
        )

        gc = _google_context(
            context=context,
            service="calendar",
            resource=resource,
            method="POST",
            body=body,
        )
        result = await self._google.execute(gc)
        return _map_create_event_result(result, self._mapper)

    async def _update_event(self, context: AdapterContext) -> AdapterResult:
        req = _build_update_event_request(context.params)
        resource = _EVENT_RESOURCE.format(
            calendar_id=req.calendar_id,
            event_id=req.event_id,
        )

        body = _build_event_body(
            summary=req.summary,
            start_time=req.start_time,
            end_time=req.end_time,
            timezone=req.timezone,
            description=req.description,
            location=req.location,
            attendees=list(req.attendees),
        )

        gc = _google_context(
            context=context,
            service="calendar",
            resource=resource,
            method="PUT",
            body=body,
        )
        result = await self._google.execute(gc)
        return _map_create_event_result(result, self._mapper)

    async def _delete_event(self, context: AdapterContext) -> AdapterResult:
        req = _build_delete_event_request(context.params)
        resource = _EVENT_RESOURCE.format(
            calendar_id=req.calendar_id,
            event_id=req.event_id,
        )

        gc = _google_context(
            context=context,
            service="calendar",
            resource=resource,
            method="DELETE",
        )
        result = await self._google.execute(gc)
        return _map_delete_result(result)


# ── Request builders ────────────────────────────────────────────────────────


def _build_list_events_request(params: dict[str, Any]) -> ListEventsRequest:
    return ListEventsRequest(
        calendar_id=params.get("calendar_id", "primary"),
        time_min=params.get("time_min", params.get("timeMin", "")),
        time_max=params.get("time_max", params.get("timeMax", "")),
        max_results=params.get("max_results", params.get("maxResults", 100)),
        query=params.get("query", params.get("q", "")),
        show_deleted=params.get("show_deleted", params.get("showDeleted", False)),
    )


def _build_get_event_request(params: dict[str, Any]) -> GetEventRequest:
    return GetEventRequest(
        event_id=params.get("event_id", params.get("id", "")),
        calendar_id=params.get("calendar_id", "primary"),
    )


def _build_create_event_request(params: dict[str, Any]) -> CreateEventRequest:
    return CreateEventRequest(
        summary=params.get("summary", ""),
        start_time=params.get("start_time", params.get("startTime", "")),
        end_time=params.get("end_time", params.get("endTime", "")),
        calendar_id=params.get("calendar_id", "primary"),
        description=params.get("description", ""),
        location=params.get("location", ""),
        timezone=params.get("timezone", "UTC"),
        attendees=tuple(params.get("attendees", [])),
    )


def _build_update_event_request(params: dict[str, Any]) -> UpdateEventRequest:
    return UpdateEventRequest(
        event_id=params.get("event_id", params.get("id", "")),
        summary=params.get("summary", ""),
        start_time=params.get("start_time", params.get("startTime", "")),
        end_time=params.get("end_time", params.get("endTime", "")),
        calendar_id=params.get("calendar_id", "primary"),
        description=params.get("description", ""),
        location=params.get("location", ""),
        timezone=params.get("timezone", "UTC"),
        attendees=tuple(params.get("attendees", [])),
    )


def _build_delete_event_request(params: dict[str, Any]) -> DeleteEventRequest:
    return DeleteEventRequest(
        event_id=params.get("event_id", params.get("id", "")),
        calendar_id=params.get("calendar_id", "primary"),
    )


# ── Event body builder ──────────────────────────────────────────────────────


def _build_event_body(
    summary: str,
    start_time: str,
    end_time: str,
    timezone: str = "UTC",
    description: str = "",
    location: str = "",
    attendees: list[str] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "summary": summary,
        "start": {
            "dateTime": start_time,
            "timeZone": timezone,
        },
        "end": {
            "dateTime": end_time,
            "timeZone": timezone,
        },
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    return body


# ── Context builder ─────────────────────────────────────────────────────────


def _google_context(
    context: AdapterContext,
    service: str,
    resource: str,
    method: str = "GET",
    query: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> AdapterContext:
    params: dict[str, Any] = {
        "service": service,
        "resource": resource,
        "method": method,
        "timeout": context.params.get("timeout", 30.0),
    }
    if query:
        params["query"] = query
    if body is not None:
        params["body"] = body
        if "content_type" not in params:
            params["content_type"] = "application/json"

    return AdapterContext.build(
        execution_session_id=context.execution_session_id,
        execution_task_id=context.execution_task_id,
        action=context.action,
        params=params,
        config=context.config,
        credentials=context.credentials,
        logger=context.logger,
    )


# ── Result mappers ──────────────────────────────────────────────────────────


def _json(result: AdapterResult) -> dict[str, Any]:
    data = result.data or {}
    json_data = data.get("json", {})
    if isinstance(json_data, dict):
        return json_data
    return {}


def _map_list_result(result: AdapterResult, mapper: CalendarResourceMapper) -> AdapterResult:
    if not result.success:
        return _with_calendar_error(result)
    data = _json(result)
    events = mapper.to_event_list(data)
    return AdapterResult(
        success=True,
        data={
            "events": events,
            "next_page_token": data.get("nextPageToken", ""),
        },
        metadata=result.metadata,
        usage=result.usage,
    )


def _map_get_event_result(result: AdapterResult, mapper: CalendarResourceMapper) -> AdapterResult:
    if not result.success:
        return _with_calendar_error(result, resource_type="event")
    data = _json(result)
    event = mapper.to_event(data)
    return AdapterResult(
        success=True,
        data={"event": event},
        metadata=result.metadata,
        usage=result.usage,
    )


def _map_create_event_result(result: AdapterResult, mapper: CalendarResourceMapper) -> AdapterResult:
    if not result.success:
        return _with_calendar_error(result)
    data = _json(result)
    event = mapper.to_event(data)
    return AdapterResult(
        success=True,
        data={
            "event": event,
            "id": event.id,
            "html_link": event.html_link,
        },
        metadata=result.metadata,
        usage=result.usage,
    )


def _map_delete_result(result: AdapterResult) -> AdapterResult:
    if not result.success:
        return _with_calendar_error(result)
    return AdapterResult(
        success=True,
        data={"deleted": True},
        metadata=result.metadata,
        usage=result.usage,
    )


# ── Error mapping ───────────────────────────────────────────────────────────


def _with_calendar_error(
    result: AdapterResult,
    resource_type: str = "",
) -> AdapterResult:
    error_msg = result.error or ""
    status_code = _status_code(result)

    if status_code == 404:
        if resource_type == "event":
            exc: CalendarError = EventNotFoundError(error_msg)
        else:
            exc = CalendarError(error_msg)
    elif status_code == 400:
        exc = InvalidEventDataError(error_msg)
    elif status_code == 403:
        exc = CalendarAccessError(error_msg)
    elif status_code == 410:
        exc = EventNotFoundError(error_msg)
    else:
        exc = CalendarError(error_msg)

    metadata = dict(result.metadata or {})
    metadata["error_type"] = type(exc).__name__
    return AdapterResult(
        success=False,
        error=str(exc),
        data=result.data,
        metadata=metadata,
        warnings=result.warnings or [],
        usage=result.usage,
    )


def _status_code(result: AdapterResult) -> int:
    data = result.data or {}
    return data.get("status_code", 0)
