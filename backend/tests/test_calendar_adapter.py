"""Comprehensive test suite for the Calendar Adapter v1.0.

Tests cover:
- Calendar request models (validation, immutability)
- Calendar response models (CalendarEvent, CalendarAttendee)
- CalendarResourceMapper (JSON → typed models)
- CalendarAdapter (list, get, create, update, delete)
- Error mapping (event not found, invalid data, access denied)
- Metadata and capability descriptors
"""

import json
import pickle
from dataclasses import FrozenInstanceError

import pytest

from services.adapters.adapter_context import AdapterContext
from services.adapters.models import AdapterMetadata, AdapterResult, UsageInfo
from services.adapters.google.calendar import (
    CalendarAdapter,
    CalendarAttendee,
    CalendarEvent,
    CalendarResourceMapper,
    CalendarError,
    EventNotFoundError,
    InvalidEventDataError,
    CalendarAccessError,
    InvalidTimeRangeError,
    ListEventsRequest,
    GetEventRequest,
    CreateEventRequest,
    UpdateEventRequest,
    DeleteEventRequest,
    CALENDAR_METADATA,
    CAPABILITY_DESCRIPTORS,
    CREDENTIAL_DESCRIPTORS,
)


# =========================================================================
# Fake Google API adapter for testing
# =========================================================================


class FakeGoogleApiAdapter:
    """Simulates GoogleApiAdapter for CalendarAdapter tests."""

    def __init__(self) -> None:
        self._responses: dict[str, AdapterResult] = {}
        self.executed_requests: list[AdapterContext] = []

    def add_response(self, resource: str, result: AdapterResult) -> None:
        self._responses[resource] = result

    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(name="google_api", display_name="", version="1")

    async def execute(self, context: AdapterContext) -> AdapterResult:
        self.executed_requests.append(context)
        resource = context.params.get("resource", "")
        response = self._responses.get(resource)
        if response is not None:
            return response
        return AdapterResult.failure_result(
            error=f"No canned response for {resource!r}",
            metadata={"error_type": "GoogleApiError"},
        )


def _google_result(data: dict) -> AdapterResult:
    return AdapterResult(
        success=True,
        data={"json": data, "status_code": 200, "body": json.dumps(data)},
        metadata={},
        usage=UsageInfo(api_calls=1, latency_ms=50.0),
    )


def _google_error(status_code: int, body: str) -> AdapterResult:
    return AdapterResult(
        success=False,
        data={"status_code": status_code, "body": body},
        metadata={"error_type": "HttpStatusError"},
        error=f"HTTP {status_code}",
    )


def _ctx(action: str, **params: object) -> AdapterContext:
    return AdapterContext.build(
        execution_session_id="s1",
        execution_task_id="t1",
        action=action,
        params=params,
        credentials={"access_token": "tok123", "token_type": "Bearer"},
    )


# =========================================================================
# Test: Calendar Request Models
# =========================================================================


class TestListEventsRequest:
    def test_defaults(self) -> None:
        req = ListEventsRequest()
        assert req.calendar_id == "primary"
        assert req.max_results == 100
        assert req.show_deleted is False

    def test_max_results_validation(self) -> None:
        with pytest.raises(ValueError, match="max_results"):
            ListEventsRequest(max_results=0)
        with pytest.raises(ValueError, match="max_results"):
            ListEventsRequest(max_results=2501)

    def test_custom_calendar_id(self) -> None:
        req = ListEventsRequest(calendar_id="secondary@group.calendar.google.com")
        assert req.calendar_id == "secondary@group.calendar.google.com"

    def test_immutable(self) -> None:
        req = ListEventsRequest()
        with pytest.raises(FrozenInstanceError):
            req.max_results = 50  # type: ignore[misc]


class TestGetEventRequest:
    def test_valid(self) -> None:
        req = GetEventRequest(event_id="evt123")
        assert req.event_id == "evt123"
        assert req.calendar_id == "primary"

    def test_empty_id_raises(self) -> None:
        with pytest.raises(ValueError, match="event_id"):
            GetEventRequest(event_id="")

    def test_immutable(self) -> None:
        req = GetEventRequest(event_id="evt1")
        with pytest.raises(FrozenInstanceError):
            req.event_id = "evt2"  # type: ignore[misc]


class TestCreateEventRequest:
    def test_valid(self) -> None:
        req = CreateEventRequest(
            summary="Meeting",
            start_time="2026-01-01T10:00:00",
            end_time="2026-01-01T11:00:00",
        )
        assert req.summary == "Meeting"
        assert req.calendar_id == "primary"
        assert req.timezone == "UTC"

    def test_empty_summary_raises(self) -> None:
        with pytest.raises(ValueError, match="summary"):
            CreateEventRequest(
                summary="",
                start_time="2026-01-01T10:00:00",
                end_time="2026-01-01T11:00:00",
            )

    def test_empty_start_time_raises(self) -> None:
        with pytest.raises(ValueError, match="start_time"):
            CreateEventRequest(
                summary="Meeting",
                start_time="",
                end_time="2026-01-01T11:00:00",
            )

    def test_empty_end_time_raises(self) -> None:
        with pytest.raises(ValueError, match="end_time"):
            CreateEventRequest(
                summary="Meeting",
                start_time="2026-01-01T10:00:00",
                end_time="",
            )

    def test_with_attendees(self) -> None:
        req = CreateEventRequest(
            summary="Meeting",
            start_time="2026-01-01T10:00:00",
            end_time="2026-01-01T11:00:00",
            attendees=("alice@example.com", "bob@example.com"),
        )
        assert len(req.attendees) == 2

    def test_immutable(self) -> None:
        req = CreateEventRequest(
            summary="Meeting",
            start_time="2026-01-01T10:00:00",
            end_time="2026-01-01T11:00:00",
        )
        with pytest.raises(FrozenInstanceError):
            req.summary = "Updated"  # type: ignore[misc]


class TestUpdateEventRequest:
    def test_valid(self) -> None:
        req = UpdateEventRequest(event_id="evt123", summary="Updated")
        assert req.event_id == "evt123"
        assert req.summary == "Updated"

    def test_empty_id_raises(self) -> None:
        with pytest.raises(ValueError, match="event_id"):
            UpdateEventRequest(event_id="")

    def test_immutable(self) -> None:
        req = UpdateEventRequest(event_id="evt1")
        with pytest.raises(FrozenInstanceError):
            req.event_id = "evt2"  # type: ignore[misc]


class TestDeleteEventRequest:
    def test_valid(self) -> None:
        req = DeleteEventRequest(event_id="evt123")
        assert req.event_id == "evt123"

    def test_empty_id_raises(self) -> None:
        with pytest.raises(ValueError, match="event_id"):
            DeleteEventRequest(event_id="")

    def test_immutable(self) -> None:
        req = DeleteEventRequest(event_id="evt1")
        with pytest.raises(FrozenInstanceError):
            req.event_id = "evt2"  # type: ignore[misc]


# =========================================================================
# Test: Response Models
# =========================================================================


class TestCalendarEvent:
    def test_fields(self) -> None:
        e = CalendarEvent(
            id="evt1",
            summary="Team Standup",
            description="Daily sync",
            location="Room 3",
            start_time="2026-01-01T09:00:00",
            end_time="2026-01-01T09:30:00",
            status="confirmed",
        )
        assert e.id == "evt1"
        assert e.summary == "Team Standup"
        assert e.status == "confirmed"

    def test_defaults(self) -> None:
        e = CalendarEvent(id="evt1")
        assert e.summary == ""
        assert e.attendees == ()
        assert e.recurrence == ()
        assert e.timezone == "UTC"

    def test_immutable(self) -> None:
        e = CalendarEvent(id="evt1")
        with pytest.raises(FrozenInstanceError):
            e.id = "evt2"  # type: ignore[misc]

    def test_pickle_roundtrip(self) -> None:
        e = CalendarEvent(id="evt1", summary="Test", status="confirmed")
        restored = pickle.loads(pickle.dumps(e))
        assert restored.id == "evt1"
        assert restored.summary == "Test"


class TestCalendarAttendee:
    def test_fields(self) -> None:
        a = CalendarAttendee(
            email="alice@example.com",
            display_name="Alice",
            response_status="accepted",
        )
        assert a.email == "alice@example.com"
        assert a.response_status == "accepted"

    def test_defaults(self) -> None:
        a = CalendarAttendee()
        assert a.email == ""
        assert a.optional is False

    def test_immutable(self) -> None:
        a = CalendarAttendee(email="a@b.com")
        with pytest.raises(FrozenInstanceError):
            a.email = "c@d.com"  # type: ignore[misc]


# =========================================================================
# Test: CalendarResourceMapper
# =========================================================================


class TestCalendarResourceMapper:
    def test_to_event_minimal(self) -> None:
        raw = {"id": "evt1", "summary": "Standup"}
        e = CalendarResourceMapper.to_event(raw)
        assert e.id == "evt1"
        assert e.summary == "Standup"

    def test_to_event_full(self) -> None:
        raw = {
            "id": "evt1",
            "summary": "Team Standup",
            "description": "Daily sync",
            "location": "Room 3",
            "start": {"dateTime": "2026-01-01T09:00:00", "timeZone": "America/New_York"},
            "end": {"dateTime": "2026-01-01T09:30:00", "timeZone": "America/New_York"},
            "status": "confirmed",
            "htmlLink": "https://calendar.google.com/event?eid=evt1",
            "created": "2025-12-01T00:00:00Z",
            "updated": "2025-12-02T00:00:00Z",
            "creator": {"email": "creator@example.com"},
            "organizer": {"email": "org@example.com"},
            "attendees": [
                {"email": "alice@example.com", "displayName": "Alice", "responseStatus": "accepted"},
            ],
            "recurrence": ["RRULE:FREQ=WEEKLY"],
            "conferenceData": {"conferenceId": "conf123"},
        }
        e = CalendarResourceMapper.to_event(raw)
        assert e.id == "evt1"
        assert e.start_time == "2026-01-01T09:00:00"
        assert e.end_time == "2026-01-01T09:30:00"
        assert e.timezone == "America/New_York"
        assert e.status == "confirmed"
        assert e.html_link == "https://calendar.google.com/event?eid=evt1"
        assert e.creator_email == "creator@example.com"
        assert e.organizer_email == "org@example.com"
        assert len(e.attendees) == 1
        assert e.attendees[0].email == "alice@example.com"
        assert e.attendees[0].response_status == "accepted"
        assert len(e.recurrence) == 1
        assert e.conference_data["conferenceId"] == "conf123"

    def test_to_event_date_only(self) -> None:
        raw = {
            "id": "evt1",
            "start": {"date": "2026-01-01"},
            "end": {"date": "2026-01-02"},
        }
        e = CalendarResourceMapper.to_event(raw)
        assert e.start_time == "2026-01-01"
        assert e.end_time == "2026-01-02"

    def test_to_event_list(self) -> None:
        raw = {
            "items": [
                {"id": "e1", "summary": "Event 1"},
                {"id": "e2", "summary": "Event 2"},
            ],
        }
        events = CalendarResourceMapper.to_event_list(raw)
        assert len(events) == 2
        assert events[0].id == "e1"
        assert events[1].summary == "Event 2"

    def test_to_event_list_empty(self) -> None:
        events = CalendarResourceMapper.to_event_list({"items": []})
        assert events == []

    def test_to_event_list_missing_items(self) -> None:
        events = CalendarResourceMapper.to_event_list({})
        assert events == []


# =========================================================================
# Test: CalendarAdapter — Error Mapping
# =========================================================================


class TestCalendarAdapterErrorMapping:
    @pytest.mark.asyncio
    async def test_event_not_found(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events/unk",
            _google_error(404, '{"error":{"code":404,"message":"Event not found","status":"NOT_FOUND"}}'),
        )
        result = await adapter.execute(_ctx("calendar_get_event", event_id="unk"))
        assert result.success is False
        assert "EventNotFoundError" in (result.metadata or {}).get("error_type", "")

    @pytest.mark.asyncio
    async def test_delete_event_not_found(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events/unk",
            _google_error(404, '{"error":{"code":404,"message":"Event not found","status":"NOT_FOUND"}}'),
        )
        result = await adapter.execute(_ctx("calendar_delete_event", event_id="unk"))
        assert result.success is False

    @pytest.mark.asyncio
    async def test_invalid_event_data(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events",
            _google_error(400, '{"error":{"code":400,"message":"Invalid event data","status":"INVALID_ARGUMENT"}}'),
        )
        result = await adapter.execute(_ctx(
            "calendar_create_event",
            summary="Invalid Data",
            start_time="not-a-valid-time",
            end_time="not-a-valid-time",
        ))
        assert result.success is False
        error_type = (result.metadata or {}).get("error_type", "")
        assert "InvalidEventData" in error_type or "CalendarError" in error_type

    @pytest.mark.asyncio
    async def test_access_denied(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events",
            _google_error(403, '{"error":{"code":403,"message":"Calendar access denied","status":"PERMISSION_DENIED"}}'),
        )
        result = await adapter.execute(_ctx("calendar_list_events"))
        assert result.success is False
        assert "CalendarAccessError" in (result.metadata or {}).get("error_type", "")

    @pytest.mark.asyncio
    async def test_auth_error_propagated(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events",
            _google_error(401, '{"error":{"code":401,"message":"Unauthorized","status":"UNAUTHENTICATED"}}'),
        )
        result = await adapter.execute(_ctx("calendar_list_events"))
        assert result.success is False
        error_type = (result.metadata or {}).get("error_type", "")
        assert "CalendarError" in error_type

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        result = await adapter.execute(_ctx("calendar_unknown"))
        assert result.success is False
        assert "Unknown Calendar action" in (result.error or "")


# =========================================================================
# Test: CalendarAdapter — List Events
# =========================================================================


class TestCalendarAdapterListEvents:
    @pytest.mark.asyncio
    async def test_list_events_success(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events",
            _google_result({
                "items": [
                    {"id": "e1", "summary": "Event 1"},
                    {"id": "e2", "summary": "Event 2"},
                ],
            }),
        )
        result = await adapter.execute(_ctx("calendar_list_events"))
        assert result.success is True
        events = result.data.get("events", [])
        assert len(events) == 2
        assert events[0].id == "e1"
        assert events[1].summary == "Event 2"

    @pytest.mark.asyncio
    async def test_list_events_with_time_range(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events",
            _google_result({"items": []}),
        )
        await adapter.execute(_ctx(
            "calendar_list_events",
            time_min="2026-01-01T00:00:00Z",
            time_max="2026-01-31T23:59:59Z",
        ))
        executed = fake.executed_requests[-1]
        query = executed.params.get("query", {})
        assert query.get("timeMin") == "2026-01-01T00:00:00Z"
        assert query.get("timeMax") == "2026-01-31T23:59:59Z"

    @pytest.mark.asyncio
    async def test_list_events_with_query(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events",
            _google_result({"items": []}),
        )
        await adapter.execute(_ctx("calendar_list_events", query="meeting"))
        executed = fake.executed_requests[-1]
        assert executed.params.get("query", {}).get("q") == "meeting"

    @pytest.mark.asyncio
    async def test_list_events_with_calendar_id(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        custom_resource = "calendars/custom@group.calendar.google.com/events"
        fake.add_response(
            custom_resource,
            _google_result({"items": [{"id": "e1"}]}),
        )
        result = await adapter.execute(_ctx(
            "calendar_list_events",
            calendar_id="custom@group.calendar.google.com",
        ))
        assert result.success is True
        executed = fake.executed_requests[-1]
        assert executed.params.get("resource") == custom_resource

    @pytest.mark.asyncio
    async def test_list_events_empty(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events",
            _google_result({"items": []}),
        )
        result = await adapter.execute(_ctx("calendar_list_events"))
        assert result.success is True
        assert result.data.get("events") == []

    @pytest.mark.asyncio
    async def test_list_events_next_page_token(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events",
            _google_result({
                "items": [{"id": "e1"}],
                "nextPageToken": "token123",
            }),
        )
        result = await adapter.execute(_ctx("calendar_list_events"))
        assert result.data.get("next_page_token") == "token123"

    @pytest.mark.asyncio
    async def test_list_events_uses_calendar_resource(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events",
            _google_result({"items": []}),
        )
        await adapter.execute(_ctx("calendar_list_events"))
        executed = fake.executed_requests[-1]
        assert executed.params.get("resource") == "calendars/primary/events"

    @pytest.mark.asyncio
    async def test_list_events_passes_credentials(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events",
            _google_result({"items": []}),
        )
        ctx = _ctx("calendar_list_events")
        await adapter.execute(ctx)
        executed = fake.executed_requests[-1]
        assert executed.credentials.get("access_token") == "tok123"


# =========================================================================
# Test: CalendarAdapter — Get Event
# =========================================================================


class TestCalendarAdapterGetEvent:
    @pytest.mark.asyncio
    async def test_get_event_success(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events/evt1",
            _google_result({
                "id": "evt1",
                "summary": "Standup",
                "start": {"dateTime": "2026-01-01T09:00:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-01-01T09:30:00", "timeZone": "UTC"},
            }),
        )
        result = await adapter.execute(_ctx("calendar_get_event", event_id="evt1"))
        assert result.success is True
        event = result.data.get("event")
        assert event.id == "evt1"
        assert event.summary == "Standup"
        assert event.start_time == "2026-01-01T09:00:00"

    @pytest.mark.asyncio
    async def test_get_event_id_alias(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events/xyz",
            _google_result({
                "id": "xyz",
                "start": {"dateTime": "2026-01-01T10:00:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-01-01T11:00:00", "timeZone": "UTC"},
            }),
        )
        result = await adapter.execute(_ctx("calendar_get_event", id="xyz"))
        assert result.success is True
        assert result.data.get("event").id == "xyz"

    @pytest.mark.asyncio
    async def test_get_event_custom_calendar(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        resource = "calendars/work@group.calendar.google.com/events/evt1"
        fake.add_response(
            resource,
            _google_result({
                "id": "evt1",
                "start": {"dateTime": "2026-01-01T10:00:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-01-01T11:00:00", "timeZone": "UTC"},
            }),
        )
        result = await adapter.execute(_ctx(
            "calendar_get_event",
            event_id="evt1",
            calendar_id="work@group.calendar.google.com",
        ))
        assert result.success is True
        executed = fake.executed_requests[-1]
        assert executed.params.get("resource") == resource


# =========================================================================
# Test: CalendarAdapter — Create Event
# =========================================================================


class TestCalendarAdapterCreateEvent:
    @pytest.mark.asyncio
    async def test_create_event_success(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events",
            _google_result({
                "id": "evt_new",
                "summary": "New Meeting",
                "htmlLink": "https://calendar.google.com/event?eid=evt_new",
                "start": {"dateTime": "2026-01-01T10:00:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-01-01T11:00:00", "timeZone": "UTC"},
            }),
        )
        result = await adapter.execute(_ctx(
            "calendar_create_event",
            summary="New Meeting",
            start_time="2026-01-01T10:00:00",
            end_time="2026-01-01T11:00:00",
        ))
        assert result.success is True
        assert result.data.get("id") == "evt_new"
        event = result.data.get("event")
        assert event.summary == "New Meeting"

    @pytest.mark.asyncio
    async def test_create_event_passes_body(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events",
            _google_result({
                "id": "evt1",
                "start": {"dateTime": "2026-01-01T10:00:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-01-01T11:00:00", "timeZone": "UTC"},
            }),
        )
        await adapter.execute(_ctx(
            "calendar_create_event",
            summary="Test",
            start_time="2026-01-01T10:00:00",
            end_time="2026-01-01T11:00:00",
            description="A test event",
            location="Conference Room A",
        ))
        executed = fake.executed_requests[-1]
        body = executed.params.get("body", {})
        assert body.get("summary") == "Test"
        assert body.get("description") == "A test event"
        assert body.get("location") == "Conference Room A"
        assert body["start"]["dateTime"] == "2026-01-01T10:00:00"
        assert body["end"]["dateTime"] == "2026-01-01T11:00:00"

    @pytest.mark.asyncio
    async def test_create_event_with_attendees(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events",
            _google_result({
                "id": "evt1",
                "start": {"dateTime": "2026-01-01T10:00:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-01-01T11:00:00", "timeZone": "UTC"},
                "attendees": [
                    {"email": "alice@example.com"},
                    {"email": "bob@example.com"},
                ],
            }),
        )
        await adapter.execute(_ctx(
            "calendar_create_event",
            summary="Team Sync",
            start_time="2026-01-01T10:00:00",
            end_time="2026-01-01T11:00:00",
            attendees=["alice@example.com", "bob@example.com"],
        ))
        executed = fake.executed_requests[-1]
        body = executed.params.get("body", {})
        assert len(body.get("attendees", [])) == 2


# =========================================================================
# Test: CalendarAdapter — Update Event
# =========================================================================


class TestCalendarAdapterUpdateEvent:
    @pytest.mark.asyncio
    async def test_update_event_success(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events/evt1",
            _google_result({
                "id": "evt1",
                "summary": "Updated Summary",
                "start": {"dateTime": "2026-01-01T10:00:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-01-01T11:00:00", "timeZone": "UTC"},
            }),
        )
        result = await adapter.execute(_ctx(
            "calendar_update_event",
            event_id="evt1",
            summary="Updated Summary",
        ))
        assert result.success is True
        event = result.data.get("event")
        assert event.summary == "Updated Summary"

    @pytest.mark.asyncio
    async def test_update_event_uses_put_method(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events/evt1",
            _google_result({
                "id": "evt1",
                "start": {"dateTime": "2026-01-01T10:00:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-01-01T11:00:00", "timeZone": "UTC"},
            }),
        )
        await adapter.execute(_ctx(
            "calendar_update_event",
            event_id="evt1",
            summary="Updated",
        ))
        executed = fake.executed_requests[-1]
        assert executed.params.get("method") == "PUT"

    @pytest.mark.asyncio
    async def test_update_event_passes_body(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events/evt1",
            _google_result({
                "id": "evt1",
                "start": {"dateTime": "2026-01-01T10:00:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-01-01T11:00:00", "timeZone": "UTC"},
            }),
        )
        await adapter.execute(_ctx(
            "calendar_update_event",
            event_id="evt1",
            summary="New Title",
            start_time="2026-01-01T14:00:00",
            end_time="2026-01-01T15:00:00",
        ))
        executed = fake.executed_requests[-1]
        body = executed.params.get("body", {})
        assert body.get("summary") == "New Title"
        assert body["start"]["dateTime"] == "2026-01-01T14:00:00"

    @pytest.mark.asyncio
    async def test_update_event_id_alias(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events/abc",
            _google_result({
                "id": "abc",
                "start": {"dateTime": "2026-01-01T10:00:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-01-01T11:00:00", "timeZone": "UTC"},
            }),
        )
        result = await adapter.execute(_ctx(
            "calendar_update_event",
            id="abc",
            summary="Changed",
        ))
        assert result.success is True


# =========================================================================
# Test: CalendarAdapter — Delete Event
# =========================================================================


class TestCalendarAdapterDeleteEvent:
    @pytest.mark.asyncio
    async def test_delete_event_success(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events/evt1",
            _google_result({"kind": "calendar#event"}),
        )
        result = await adapter.execute(_ctx("calendar_delete_event", event_id="evt1"))
        assert result.success is True
        assert result.data.get("deleted") is True

    @pytest.mark.asyncio
    async def test_delete_event_uses_delete_method(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events/evt1",
            _google_result({"kind": "calendar#event"}),
        )
        await adapter.execute(_ctx("calendar_delete_event", event_id="evt1"))
        executed = fake.executed_requests[-1]
        assert executed.params.get("method") == "DELETE"

    @pytest.mark.asyncio
    async def test_delete_event_id_alias(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events/xyz",
            _google_result({"kind": "calendar#event"}),
        )
        result = await adapter.execute(_ctx("calendar_delete_event", id="xyz"))
        assert result.success is True


# =========================================================================
# Test: CalendarAdapter — Metadata & Capabilities
# =========================================================================


class TestCalendarAdapterMetadata:
    def test_metadata_name(self) -> None:
        assert CALENDAR_METADATA.name == "calendar"

    def test_metadata_version(self) -> None:
        assert CALENDAR_METADATA.version == "1.0.0"

    def test_metadata_requires_auth(self) -> None:
        assert CALENDAR_METADATA.requires_auth is True

    def test_metadata_tags_include_calendar(self) -> None:
        assert "calendar" in CALENDAR_METADATA.tags

    @pytest.mark.asyncio
    async def test_adapter_metadata_property(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        meta = adapter.metadata
        assert meta.name == "calendar"

    def test_capability_descriptors(self) -> None:
        names = [c["name"] for c in CAPABILITY_DESCRIPTORS]
        assert "calendar_list_events" in names
        assert "calendar_get_event" in names
        assert "calendar_create_event" in names
        assert "calendar_update_event" in names
        assert "calendar_delete_event" in names
        assert len(names) == 5

    def test_capability_versions(self) -> None:
        for c in CAPABILITY_DESCRIPTORS:
            assert c["version"] == "1.0.0"
            assert c["requires_auth"] is True

    def test_credential_descriptor_reuses_google_oauth2(self) -> None:
        assert len(CREDENTIAL_DESCRIPTORS) == 1
        assert CREDENTIAL_DESCRIPTORS[0]["name"] == "google_oauth2"

    def test_supported_operations_in_metadata(self) -> None:
        ops = CALENDAR_METADATA.supported_operations
        assert "calendar_list_events" in ops
        assert "calendar_get_event" in ops
        assert "calendar_create_event" in ops
        assert "calendar_update_event" in ops
        assert "calendar_delete_event" in ops
        assert len(ops) == 5


# =========================================================================
# Test: CalendarAdapter — Stateless & No Caching
# =========================================================================


class TestCalendarAdapterStateless:
    @pytest.mark.asyncio
    async def test_no_mutable_state(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "calendars/primary/events",
            _google_result({"items": []}),
        )
        await adapter.execute(_ctx("calendar_list_events"))
        await adapter.execute(_ctx("calendar_list_events"))
        assert len(fake.executed_requests) == 2

    def test_no_caching_in_source(self) -> None:
        from services.adapters.google.calendar import calendar_adapter
        import inspect
        source = inspect.getsource(calendar_adapter)
        assert "cache" not in source.lower()

    def test_no_retry_implementation(self) -> None:
        from services.adapters.google.calendar import calendar_adapter
        import inspect
        source = inspect.getsource(calendar_adapter)
        assert "while" not in source.lower()
        assert "backoff" not in source.lower()
        assert "tenacity" not in source.lower()


# =========================================================================
# Test: CalendarAdapter — No Lower-Layer Dependency
# =========================================================================


class TestCalendarAdapterNoLowerDependencies:
    def test_no_runtime_import(self) -> None:
        import services.adapters.google.calendar.calendar_adapter as mod
        import inspect
        source = inspect.getsource(mod)
        assert "services.execution" not in source
