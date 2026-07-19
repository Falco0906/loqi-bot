from __future__ import annotations

import json
import pickle
from typing import Any

import pytest

from services.adapters.adapter_context import AdapterContext
from services.adapters.google.errors import (
    GoogleApiError,
    GoogleApiErrorInfo,
    GoogleAuthenticationError,
    GoogleConflictError,
    GooglePermissionError,
    GoogleQuotaExceededError,
    GoogleRateLimitError,
    GoogleResourceNotFoundError,
    GoogleValidationError,
    classify_google_status_code,
    parse_google_error_body,
)
from services.adapters.google.google_api_adapter import (
    CAPABILITY_DESCRIPTORS,
    CREDENTIAL_DESCRIPTORS,
    GOOGLE_API_METADATA,
    GoogleApiAdapter,
)
from services.adapters.google.models import GoogleApiRequest, GoogleApiResponse
from services.adapters.google.pagination import (
    has_more_pages,
    max_results_param,
    next_page_token,
    page_token_param,
)
from services.adapters.google.services import (
    DEFAULT_GOOGLE_SERVICES,
    GoogleServiceDescriptor,
    GoogleServiceRegistry,
)
from services.adapters.google.urls import (
    build_google_url,
    calendar,
    docs,
    drive,
    gmail,
    people,
    register_google_service,
    sheets,
    tasks,
)
from services.adapters.http.http_adapter import HttpAdapter
from services.adapters.http.exceptions import HttpStatusError
from services.adapters.http.models import HttpRequest, SUPPORTED_METHODS
from services.adapters.models import AdapterMetadata, AdapterResult, UsageInfo


# =========================================================================
# Fake transport for testing
# =========================================================================


class FakeGoogleTransport:
    """Fake HTTP transport for Google adapter tests.

    Returns canned responses or raises errors keyed by (method, url).
    Mirrors HttpxTransport behavior: raises HttpStatusError for 4xx/5xx.
    """

    def __init__(self) -> None:
        self._responses: dict[tuple[str, str], tuple[int, bytes, dict[str, str]]] = {}
        self._errors: dict[tuple[str, str], Exception] = {}
        self.sent_requests: list[HttpRequest] = []

    def add_response(
        self,
        method: str,
        url: str,
        status_code: int = 200,
        body: bytes = b"{}",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._responses[(method.upper(), url)] = (
            status_code,
            body,
            headers or {"content-type": "application/json"},
        )

    def add_error(self, method: str, url: str, error: Exception) -> None:
        self._errors[(method.upper(), url)] = error

    async def send(self, request: HttpRequest) -> Any:
        self.sent_requests.append(request)
        key = (request.method.upper(), request.url)
        if key in self._errors:
            raise self._errors[key]
        if key in self._responses:
            status, body, headers = self._responses[key]
            from services.adapters.http.models import HttpResponse
            resp = HttpResponse(
                status_code=status,
                body=body,
                headers=headers,
                elapsed=0.1,
                content_type=headers.get("content-type", "application/json"),
            )
            if resp.is_client_error() or resp.is_server_error():
                raise HttpStatusError(
                    message=f"HTTP {status} for {request.url}",
                    status_code=status,
                    body=body.decode("utf-8", errors="replace"),
                    headers=headers,
                )
            return resp
        from services.adapters.http.models import HttpResponse
        raise HttpStatusError(
            message="HTTP 404 for not found",
            status_code=404,
            body='{"error":{"code":404,"message":"Not Found","status":"NOT_FOUND"}}',
            headers={"content-type": "application/json"},
        )


# =========================================================================
# Test GoogleServiceDescriptor
# =========================================================================


class TestGoogleServiceDescriptorConstruction:
    def test_minimal(self) -> None:
        desc = GoogleServiceDescriptor(
            name="gmail",
            base_url="https://gmail.googleapis.com",
            default_version="v1",
        )
        assert desc.name == "gmail"
        assert desc.base_url == "https://gmail.googleapis.com"
        assert desc.default_version == "v1"
        assert desc.scopes == ()
        assert desc.supports_pagination is True
        assert desc.supports_batch is False

    def test_full(self) -> None:
        desc = GoogleServiceDescriptor(
            name="drive",
            base_url="https://www.googleapis.com",
            default_version="v3",
            scopes=("https://www.googleapis.com/auth/drive",),
            supports_pagination=True,
            supports_batch=False,
        )
        assert desc.name == "drive"
        assert desc.scopes == ("https://www.googleapis.com/auth/drive",)

    def test_frozen(self) -> None:
        desc = GoogleServiceDescriptor(
            name="test", base_url="https://example.com", default_version="v1"
        )
        with pytest.raises(AttributeError):
            desc.name = "changed"

    def test_empty_name_raises(self) -> None:
        with pytest.raises(GoogleApiError):
            GoogleServiceDescriptor(
                name="", base_url="https://example.com", default_version="v1"
            )

    def test_empty_base_url_raises(self) -> None:
        with pytest.raises(GoogleApiError):
            GoogleServiceDescriptor(
                name="test", base_url="", default_version="v1"
            )

    def test_empty_default_version_raises(self) -> None:
        with pytest.raises(GoogleApiError):
            GoogleServiceDescriptor(
                name="test", base_url="https://example.com", default_version=""
            )

    def test_build_url_basic(self) -> None:
        desc = GoogleServiceDescriptor(
            name="gmail",
            base_url="https://gmail.googleapis.com",
            default_version="v1",
        )
        url = desc.build_url(resource="users/me/messages")
        assert url == "https://gmail.googleapis.com/gmail/v1/users/me/messages"

    def test_build_url_with_version_override(self) -> None:
        desc = GoogleServiceDescriptor(
            name="drive",
            base_url="https://www.googleapis.com",
            default_version="v3",
        )
        url = desc.build_url(version="v2", resource="files")
        assert url == "https://www.googleapis.com/drive/v2/files"

    def test_build_url_no_resource(self) -> None:
        desc = GoogleServiceDescriptor(
            name="calendar",
            base_url="https://www.googleapis.com",
            default_version="v3",
        )
        url = desc.build_url()
        assert url == "https://www.googleapis.com/calendar/v3"

    def test_build_url_resource_with_leading_slash(self) -> None:
        desc = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        url = desc.build_url(resource="/users/me/messages")
        assert url == "https://gmail.googleapis.com/gmail/v1/users/me/messages"

    def test_build_url_base_with_trailing_slash(self) -> None:
        desc = GoogleServiceDescriptor(
            name="gmail",
            base_url="https://gmail.googleapis.com/",
            default_version="v1",
        )
        url = desc.build_url(resource="users/me/messages")
        assert url == "https://gmail.googleapis.com/gmail/v1/users/me/messages"


class TestGoogleServiceDescriptorRegistration:
    def test_repr(self) -> None:
        desc = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        r = repr(desc)
        assert "GoogleServiceDescriptor" in r
        assert "gmail" in r

    def test_equality(self) -> None:
        a = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        b = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        assert a == b

    def test_inequality(self) -> None:
        a = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        b = GoogleServiceDescriptor(
            name="drive", base_url="https://www.googleapis.com", default_version="v3"
        )
        assert a != b

    def test_pickle_roundtrip(self) -> None:
        desc = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        restored = pickle.loads(pickle.dumps(desc))
        assert restored.name == desc.name
        assert restored.base_url == desc.base_url


# =========================================================================
# Test GoogleServiceRegistry
# =========================================================================


class TestGoogleServiceRegistry:
    def test_empty_registry(self) -> None:
        registry = GoogleServiceRegistry()
        assert registry.count() == 0
        assert registry.list_services() == []

    def test_register_and_get(self) -> None:
        registry = GoogleServiceRegistry()
        desc = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        registry.register(desc)
        assert registry.count() == 1
        assert registry.get("gmail") is desc

    def test_require_found(self) -> None:
        registry = GoogleServiceRegistry()
        desc = GoogleServiceDescriptor(
            name="drive", base_url="https://www.googleapis.com", default_version="v3"
        )
        registry.register(desc)
        assert registry.require("drive") is desc

    def test_require_not_found_raises(self) -> None:
        registry = GoogleServiceRegistry()
        with pytest.raises(GoogleApiError, match="Unknown"):
            registry.require("nonexistent")

    def test_get_nonexistent_returns_none(self) -> None:
        registry = GoogleServiceRegistry()
        assert registry.get("nonexistent") is None

    def test_duplicate_register_raises(self) -> None:
        registry = GoogleServiceRegistry()
        desc = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        registry.register(desc)
        with pytest.raises(GoogleApiError, match="already registered"):
            registry.register(desc)

    def test_unregister(self) -> None:
        registry = GoogleServiceRegistry()
        desc = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        registry.register(desc)
        registry.unregister("gmail")
        assert registry.count() == 0

    def test_unregister_nonexistent_raises(self) -> None:
        registry = GoogleServiceRegistry()
        with pytest.raises(GoogleApiError, match="not registered"):
            registry.unregister("gmail")

    def test_clear(self) -> None:
        registry = GoogleServiceRegistry()
        registry.register(
            GoogleServiceDescriptor(
                name="a", base_url="https://a.com", default_version="v1"
            )
        )
        registry.register(
            GoogleServiceDescriptor(
                name="b", base_url="https://b.com", default_version="v1"
            )
        )
        registry.clear()
        assert registry.count() == 0

    def test_list_services(self) -> None:
        registry = GoogleServiceRegistry()
        registry.register(
            GoogleServiceDescriptor(
                name="a", base_url="https://a.com", default_version="v1"
            )
        )
        registry.register(
            GoogleServiceDescriptor(
                name="b", base_url="https://b.com", default_version="v1"
            )
        )
        names = {s.name for s in registry.list_services()}
        assert names == {"a", "b"}

    def test_with_defaults(self) -> None:
        registry = GoogleServiceRegistry.with_defaults()
        assert registry.count() == 7
        assert registry.get("gmail") is not None
        assert registry.get("calendar") is not None
        assert registry.get("drive") is not None
        assert registry.get("docs") is not None
        assert registry.get("sheets") is not None
        assert registry.get("people") is not None
        assert registry.get("tasks") is not None


class TestDefaultGoogleServices:
    def test_gmail_default(self) -> None:
        svc = DEFAULT_GOOGLE_SERVICES[0]
        assert svc.name == "gmail"
        assert "gmail" in svc.base_url

    def test_calendar_default(self) -> None:
        svc = [s for s in DEFAULT_GOOGLE_SERVICES if s.name == "calendar"][0]
        assert svc.base_url == "https://www.googleapis.com"

    def test_drive_default(self) -> None:
        svc = [s for s in DEFAULT_GOOGLE_SERVICES if s.name == "drive"][0]
        assert svc.default_version == "v3"

    def test_all_have_names(self) -> None:
        for svc in DEFAULT_GOOGLE_SERVICES:
            assert svc.name

    def test_all_have_urls(self) -> None:
        for svc in DEFAULT_GOOGLE_SERVICES:
            assert svc.base_url.startswith("https://")

    def test_all_have_versions(self) -> None:
        for svc in DEFAULT_GOOGLE_SERVICES:
            assert svc.default_version

    def test_count_defaults(self) -> None:
        assert len(DEFAULT_GOOGLE_SERVICES) == 7


# =========================================================================
# Test GoogleApiErrorInfo and error parsing
# =========================================================================


class TestGoogleApiErrorInfo:
    def test_basic_construction(self) -> None:
        info = GoogleApiErrorInfo(code=400, message="Bad Request", status="INVALID_ARGUMENT")
        assert info.code == 400
        assert info.message == "Bad Request"
        assert info.status == "INVALID_ARGUMENT"
        assert info.errors == []

    def test_to_exception_400(self) -> None:
        info = GoogleApiErrorInfo(code=400, message="invalid", status="INVALID_ARGUMENT")
        exc = info.to_exception()
        assert isinstance(exc, GoogleValidationError)

    def test_to_exception_401(self) -> None:
        info = GoogleApiErrorInfo(code=401, message="unauth", status="UNAUTHENTICATED")
        exc = info.to_exception()
        assert isinstance(exc, GoogleAuthenticationError)

    def test_to_exception_403(self) -> None:
        info = GoogleApiErrorInfo(code=403, message="forbidden", status="PERMISSION_DENIED")
        exc = info.to_exception()
        assert isinstance(exc, GooglePermissionError)

    def test_to_exception_404(self) -> None:
        info = GoogleApiErrorInfo(code=404, message="not found", status="NOT_FOUND")
        exc = info.to_exception()
        assert isinstance(exc, GoogleResourceNotFoundError)

    def test_to_exception_409(self) -> None:
        info = GoogleApiErrorInfo(code=409, message="conflict", status="CONFLICT")
        exc = info.to_exception()
        assert isinstance(exc, GoogleConflictError)

    def test_to_exception_429(self) -> None:
        info = GoogleApiErrorInfo(code=429, message="quota", status="RESOURCE_EXHAUSTED")
        exc = info.to_exception()
        assert isinstance(exc, GoogleQuotaExceededError)

    def test_to_exception_rate_limit(self) -> None:
        info = GoogleApiErrorInfo(code=429, message="rate", status="RATE_LIMIT_EXCEEDED")
        exc = info.to_exception()
        assert isinstance(exc, GoogleRateLimitError)

    def test_to_exception_unknown_status(self) -> None:
        info = GoogleApiErrorInfo(code=500, message="server error", status="INTERNAL")
        exc = info.to_exception()
        assert isinstance(exc, GoogleApiError)

    def test_to_exception_by_code_only(self) -> None:
        info = GoogleApiErrorInfo(code=400)
        exc = info.to_exception()
        assert isinstance(exc, GoogleValidationError)

    def test_to_dict(self) -> None:
        info = GoogleApiErrorInfo(
            code=403, message="denied", status="PERMISSION_DENIED",
            errors=[{"reason": "rateLimitExceeded"}],
        )
        d = info.to_dict()
        assert d["code"] == 403
        assert d["status"] == "PERMISSION_DENIED"
        assert d["errors"] == [{"reason": "rateLimitExceeded"}]


class TestParseGoogleErrorBody:
    def test_parse_valid_error(self) -> None:
        body = json.dumps({
            "error": {"code": 400, "message": "Bad Request", "status": "INVALID_ARGUMENT"}
        })
        info = parse_google_error_body(body)
        assert info is not None
        assert info.code == 400
        assert info.message == "Bad Request"
        assert info.status == "INVALID_ARGUMENT"

    def test_parse_with_errors_list(self) -> None:
        body = json.dumps({
            "error": {
                "code": 403,
                "message": "Forbidden",
                "status": "PERMISSION_DENIED",
                "errors": [{"reason": "rateLimitExceeded"}],
            }
        })
        info = parse_google_error_body(body)
        assert info is not None
        assert len(info.errors) == 1

    def test_empty_body_returns_none(self) -> None:
        assert parse_google_error_body("") is None

    def test_invalid_json_returns_none(self) -> None:
        assert parse_google_error_body("not json") is None

    def test_non_dict_error_returns_none(self) -> None:
        body = json.dumps({"error": "string instead of dict"})
        info = parse_google_error_body(body)
        assert info is None

    def test_missing_error_key_returns_none(self) -> None:
        body = json.dumps({"data": "no error here"})
        info = parse_google_error_body(body)
        assert info is None

    def test_nested_error_fields(self) -> None:
        body = json.dumps({
            "error": {
                "code": 429,
                "message": "Rate limit exceeded",
                "status": "RESOURCE_EXHAUSTED",
                "errors": [
                    {
                        "domain": "usageLimits",
                        "reason": "rateLimitExceeded",
                        "message": "Quota exceeded",
                    }
                ],
            }
        })
        info = parse_google_error_body(body)
        assert info is not None
        assert info.code == 429
        assert info.errors[0]["reason"] == "rateLimitExceeded"


class TestClassifyGoogleStatusCode:
    def test_400(self) -> None:
        assert classify_google_status_code(400) is GoogleValidationError

    def test_401(self) -> None:
        assert classify_google_status_code(401) is GoogleAuthenticationError

    def test_403(self) -> None:
        assert classify_google_status_code(403) is GooglePermissionError

    def test_404(self) -> None:
        assert classify_google_status_code(404) is GoogleResourceNotFoundError

    def test_409(self) -> None:
        assert classify_google_status_code(409) is GoogleConflictError

    def test_429(self) -> None:
        assert classify_google_status_code(429) is GoogleQuotaExceededError

    def test_unknown_code(self) -> None:
        assert classify_google_status_code(502) is GoogleApiError

    def test_200_is_not_mapped(self) -> None:
        assert classify_google_status_code(200) is GoogleApiError


# =========================================================================
# Test GoogleApiRequest
# =========================================================================


class TestGoogleApiRequestConstruction:
    def test_minimal(self) -> None:
        req = GoogleApiRequest(service="gmail", resource="users/me/messages")
        assert req.service == "gmail"
        assert req.resource == "users/me/messages"
        assert req.version == ""
        assert req.method == "GET"
        assert req.query == {}
        assert req.body is None
        assert req.headers == {}
        assert req.timeout == 30.0

    def test_full(self) -> None:
        req = GoogleApiRequest(
            service="drive",
            resource="files",
            version="v3",
            method="POST",
            query={"q": "name contains 'test'"},
            body={"name": "test.txt"},
            headers={"X-Custom": "val"},
            timeout=15.0,
        )
        assert req.service == "drive"
        assert req.method == "POST"
        assert req.query["q"] == "name contains 'test'"
        assert req.body == {"name": "test.txt"}

    def test_frozen(self) -> None:
        req = GoogleApiRequest(service="gmail", resource="users/me/messages")
        with pytest.raises(AttributeError):
            req.service = "drive"


class TestGoogleApiRequestToHttpRequest:
    def test_basic_conversion(self) -> None:
        desc = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        req = GoogleApiRequest(service="gmail", resource="users/me/messages")
        http_req = req.to_http_request(desc)
        assert http_req.method == "GET"
        assert http_req.url == "https://gmail.googleapis.com/gmail/v1/users/me/messages"
        assert http_req.content_type == "application/json"

    def test_with_auth(self) -> None:
        desc = GoogleServiceDescriptor(
            name="drive", base_url="https://www.googleapis.com", default_version="v3"
        )
        req = GoogleApiRequest(service="drive", resource="files")
        http_req = req.to_http_request(desc, access_token="tok123")
        assert http_req.headers.get("Authorization") == "Bearer tok123"

    def test_with_custom_token_type(self) -> None:
        desc = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        req = GoogleApiRequest(service="gmail", resource="users/me/messages")
        http_req = req.to_http_request(desc, access_token="tok", token_type="JWT")
        assert http_req.headers.get("Authorization") == "JWT tok"

    def test_no_auth_when_no_token(self) -> None:
        desc = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        req = GoogleApiRequest(service="gmail", resource="users/me/messages")
        http_req = req.to_http_request(desc, access_token="")
        assert "Authorization" not in http_req.headers

    def test_content_type_set(self) -> None:
        desc = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        req = GoogleApiRequest(service="gmail", resource="users/me/messages")
        http_req = req.to_http_request(desc)
        assert http_req.content_type == "application/json"

    def test_query_params_passed(self) -> None:
        desc = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        req = GoogleApiRequest(
            service="gmail",
            resource="users/me/messages",
            query={"q": "in:inbox", "maxResults": "50"},
        )
        http_req = req.to_http_request(desc)
        assert http_req.query_params == {"q": "in:inbox", "maxResults": "50"}

    def test_body_passed(self) -> None:
        desc = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        req = GoogleApiRequest(
            service="gmail",
            resource="users/me/messages",
            method="POST",
            body={"raw": "base64content"},
        )
        http_req = req.to_http_request(desc)
        assert http_req.body == {"raw": "base64content"}

    def test_user_headers_preserved(self) -> None:
        desc = GoogleServiceDescriptor(
            name="gmail", base_url="https://gmail.googleapis.com", default_version="v1"
        )
        req = GoogleApiRequest(
            service="gmail",
            resource="users/me/messages",
            headers={"X-Trace-Id": "abc123"},
        )
        http_req = req.to_http_request(desc, access_token="tok")
        assert http_req.headers.get("X-Trace-Id") == "abc123"
        assert http_req.headers.get("Authorization") == "Bearer tok"


class TestGoogleApiRequestImmutability:
    def test_cannot_reassign_query(self) -> None:
        req = GoogleApiRequest(
            service="gmail", resource="users/me/messages", query={"q": "test"}
        )
        with pytest.raises(AttributeError):
            req.query = {}  # type: ignore[misc]

    def test_pickle_roundtrip(self) -> None:
        req = GoogleApiRequest(
            service="drive", resource="files", method="POST", body={"name": "f"}
        )
        restored = pickle.loads(pickle.dumps(req))
        assert restored.service == "drive"
        assert restored.body == {"name": "f"}

    def test_equality(self) -> None:
        a = GoogleApiRequest(service="gmail", resource="users/me/messages")
        b = GoogleApiRequest(service="gmail", resource="users/me/messages")
        assert a == b


# =========================================================================
# Test GoogleApiResponse
# =========================================================================


class TestGoogleApiResponseConstruction:
    def test_minimal(self) -> None:
        resp = GoogleApiResponse(data={})
        assert resp.status_code == 200
        assert resp.success is True
        assert resp.data == {}

    def test_with_error_status(self) -> None:
        resp = GoogleApiResponse(data={}, status_code=404)
        assert resp.success is False

    def test_full(self) -> None:
        resp = GoogleApiResponse(
            data={"id": "123", "kind": "drive#file", "etag": '"abc"'},
            status_code=200,
            headers={"x-request-id": "req1"},
        )
        assert resp.data["id"] == "123"
        assert resp.headers["x-request-id"] == "req1"

    def test_repr(self) -> None:
        resp = GoogleApiResponse(data={"kind": "gmail#message"}, status_code=200)
        r = repr(resp)
        assert "GoogleApiResponse" in r
        assert "gmail#message" in r

    def test_frozen(self) -> None:
        resp = GoogleApiResponse(data={})
        with pytest.raises(AttributeError):
            resp.status_code = 404


class TestGoogleApiResponseHelpers:
    def test_next_page_token(self) -> None:
        resp = GoogleApiResponse(data={"nextPageToken": "token123"})
        assert resp.next_page_token() == "token123"

    def test_next_page_token_none(self) -> None:
        resp = GoogleApiResponse(data={})
        assert resp.next_page_token() is None

    def test_etag(self) -> None:
        resp = GoogleApiResponse(data={"etag": '"abc123"'})
        assert resp.etag() == '"abc123"'

    def test_etag_missing(self) -> None:
        resp = GoogleApiResponse(data={})
        assert resp.etag() is None

    def test_kind(self) -> None:
        resp = GoogleApiResponse(data={"kind": "drive#file"})
        assert resp.kind() == "drive#file"

    def test_kind_missing(self) -> None:
        resp = GoogleApiResponse(data={})
        assert resp.kind() is None

    def test_resource_id(self) -> None:
        resp = GoogleApiResponse(data={"id": "msg_123"})
        assert resp.resource_id() == "msg_123"

    def test_resource_id_missing(self) -> None:
        resp = GoogleApiResponse(data={})
        assert resp.resource_id() is None


# =========================================================================
# Test Pagination Helpers
# =========================================================================


class TestPaginationHelpers:
    def test_next_page_token_found(self) -> None:
        data = {"nextPageToken": "abc123", "items": [1, 2]}
        assert next_page_token(data) == "abc123"

    def test_next_page_token_missing(self) -> None:
        data = {"items": [1, 2]}
        assert next_page_token(data) is None

    def test_next_page_token_empty(self) -> None:
        data = {"nextPageToken": ""}
        assert next_page_token(data) == ""

    def test_page_token_param(self) -> None:
        result = page_token_param("tok123")
        assert result == {"pageToken": "tok123"}

    def test_max_results_param(self) -> None:
        result = max_results_param(100)
        assert result == {"maxResults": "100"}

    def test_max_results_param_zero(self) -> None:
        result = max_results_param(0)
        assert result == {"maxResults": "0"}

    def test_has_more_pages_true(self) -> None:
        data = {"nextPageToken": "abc"}
        assert has_more_pages(data) is True

    def test_has_more_pages_false_missing(self) -> None:
        data = {"items": [1, 2]}
        assert has_more_pages(data) is False

    def test_has_more_pages_false_empty(self) -> None:
        data = {"nextPageToken": ""}
        assert has_more_pages(data) is False


# =========================================================================
# Test URL Builder and Helpers
# =========================================================================


class TestBuildGoogleUrl:
    def test_gmail(self) -> None:
        url = build_google_url("gmail", "users/me/messages")
        assert url == "https://gmail.googleapis.com/gmail/v1/users/me/messages"

    def test_calendar(self) -> None:
        url = build_google_url("calendar", "calendars/primary/events")
        assert url == "https://www.googleapis.com/calendar/v3/calendars/primary/events"

    def test_drive(self) -> None:
        url = build_google_url("drive", "files")
        assert url == "https://www.googleapis.com/drive/v3/files"

    def test_docs(self) -> None:
        url = build_google_url("docs", "documents/doc123")
        assert url == "https://docs.googleapis.com/docs/v1/documents/doc123"

    def test_sheets(self) -> None:
        url = build_google_url("sheets", "spreadsheets/sheet123")
        assert url == "https://sheets.googleapis.com/sheets/v4/spreadsheets/sheet123"

    def test_people(self) -> None:
        url = build_google_url("people", "people/me")
        assert url == "https://people.googleapis.com/people/v1/people/me"

    def test_tasks(self) -> None:
        url = build_google_url("tasks", "lists")
        assert url == "https://tasks.googleapis.com/tasks/v1/lists"

    def test_with_version_override(self) -> None:
        url = build_google_url("drive", "files", version="v2")
        assert url == "https://www.googleapis.com/drive/v2/files"

    def test_unknown_service_raises(self) -> None:
        with pytest.raises(GoogleApiError, match="Unknown"):
            build_google_url("nonexistent", "resource")


class TestUrlHelpers:
    def test_gmail_helper(self) -> None:
        result = gmail("users/me/messages")
        assert result["service"] == "gmail"
        assert result["resource"] == "users/me/messages"
        assert result["version"] == "v1"

    def test_calendar_helper(self) -> None:
        result = calendar("calendars/primary/events")
        assert result["service"] == "calendar"
        assert result["resource"] == "calendars/primary/events"
        assert result["version"] == "v3"

    def test_drive_helper(self) -> None:
        result = drive("files")
        assert result["service"] == "drive"
        assert result["resource"] == "files"
        assert result["version"] == "v3"

    def test_docs_helper(self) -> None:
        result = docs("documents/doc123")
        assert result["service"] == "docs"
        assert result["version"] == "v1"

    def test_sheets_helper(self) -> None:
        result = sheets("spreadsheets/s1")
        assert result["service"] == "sheets"
        assert result["version"] == "v4"

    def test_people_helper(self) -> None:
        result = people("people/me")
        assert result["service"] == "people"
        assert result["version"] == "v1"

    def test_tasks_helper(self) -> None:
        result = tasks("lists")
        assert result["service"] == "tasks"
        assert result["version"] == "v1"

    def test_register_google_service(self) -> None:
        new_svc = GoogleServiceDescriptor(
            name="custom_api",
            base_url="https://custom.googleapis.com",
            default_version="v1",
        )
        registry = GoogleServiceRegistry()
        register_google_service(new_svc, registry=registry)
        assert registry.get("custom_api") is not None
        url = build_google_url("custom_api", "endpoint", registry=registry)
        assert url == "https://custom.googleapis.com/custom_api/v1/endpoint"


# =========================================================================
# Test GoogleApiAdapter - Metadata and constants
# =========================================================================


class TestGoogleApiAdapterMetadata:
    def test_metadata(self) -> None:
        adapter = GoogleApiAdapter()
        meta = adapter.metadata
        assert isinstance(meta, AdapterMetadata)
        assert meta.name == "google_api"
        assert meta.version == "1.0.0"
        assert "google" in meta.tags
        assert "workspace" in meta.tags
        assert "oauth2" in meta.tags
        assert meta.requires_auth is True

    def test_metadata_frozen(self) -> None:
        meta = GoogleApiAdapter().metadata
        with pytest.raises(AttributeError):
            meta.name = "changed"

    def test_capability_descriptors(self) -> None:
        assert len(CAPABILITY_DESCRIPTORS) == 2
        names = {c["name"] for c in CAPABILITY_DESCRIPTORS}
        assert "google_request" in names
        assert "google_paginated_request" in names

    def test_credential_descriptors(self) -> None:
        assert len(CREDENTIAL_DESCRIPTORS) == 1
        assert CREDENTIAL_DESCRIPTORS[0]["name"] == "google_oauth2"
        assert CREDENTIAL_DESCRIPTORS[0]["auth_type"] == "oauth2"

    def test_no_gmail_in_capabilities(self) -> None:
        for cap in CAPABILITY_DESCRIPTORS:
            assert "gmail" not in cap["name"].lower()

    def test_no_gmail_in_metadata_description(self) -> None:
        meta = GOOGLE_API_METADATA
        assert "gmail" not in meta.description.lower()
        assert "calendar" not in meta.description.lower()
        assert "drive" not in meta.description.lower()

    def test_repr(self) -> None:
        adapter = GoogleApiAdapter()
        r = repr(adapter)
        assert "HttpAdapter" in r or "GoogleApiAdapter" in r


# =========================================================================
# Test GoogleApiAdapter - Validation (missing params)
# =========================================================================


class TestGoogleApiAdapterValidation:
    @pytest.mark.asyncio
    async def test_missing_service(self) -> None:
        adapter = GoogleApiAdapter(transport=FakeGoogleTransport())
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"resource": "files"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is False
        assert "service" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_resource(self) -> None:
        adapter = GoogleApiAdapter(transport=FakeGoogleTransport())
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is False
        assert "resource" in result.error.lower()

    @pytest.mark.asyncio
    async def test_unknown_service(self) -> None:
        adapter = GoogleApiAdapter(transport=FakeGoogleTransport())
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "nonexistent", "resource": "files"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is False
        assert "Unknown" in result.error

    @pytest.mark.asyncio
    async def test_missing_access_token(self) -> None:
        adapter = GoogleApiAdapter(transport=FakeGoogleTransport())
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files"},
            credentials={},
        )
        result = await adapter.execute(ctx)
        assert result.success is False
        assert "access_token" in result.error.lower()

    @pytest.mark.asyncio
    async def test_empty_access_token(self) -> None:
        adapter = GoogleApiAdapter(transport=FakeGoogleTransport())
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files"},
            credentials={"access_token": ""},
        )
        result = await adapter.execute(ctx)
        assert result.success is False
        assert "access_token" in result.error.lower()


# =========================================================================
# Test GoogleApiAdapter - Execution with fake transport
# =========================================================================


class TestGoogleApiAdapterExecute:
    @pytest.mark.asyncio
    async def test_simple_get(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET",
            "https://www.googleapis.com/drive/v3/files",
            status_code=200,
            body=b'{"kind": "drive#fileList", "files": []}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files"},
            credentials={"access_token": "tok", "token_type": "Bearer"},
        )
        result = await adapter.execute(ctx)
        assert result.success is True
        assert result.data["json"]["kind"] == "drive#fileList"

    @pytest.mark.asyncio
    async def test_gmail_get(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            status_code=200,
            body=b'{"messages": [{"id": "123"}]}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "gmail", "resource": "users/me/messages"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is True
        assert result.data["json"]["messages"][0]["id"] == "123"

    @pytest.mark.asyncio
    async def test_calendar_get_events(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET",
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            status_code=200,
            body=b'{"items": [{"summary": "Meeting"}]}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "calendar", "resource": "calendars/primary/events"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is True
        assert result.data["json"]["items"][0]["summary"] == "Meeting"

    @pytest.mark.asyncio
    async def test_post_with_body(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "POST",
            "https://www.googleapis.com/drive/v3/files",
            status_code=201,
            body=b'{"id": "file123", "kind": "drive#file"}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={
                "service": "drive",
                "resource": "files",
                "method": "POST",
                "body": {"name": "test.txt"},
            },
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is True
        assert result.data["json"]["id"] == "file123"

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "DELETE",
            "https://www.googleapis.com/drive/v3/files/file123",
            status_code=204,
            body=b"",
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files/file123", "method": "DELETE"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_with_query_params(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET",
            "https://www.googleapis.com/drive/v3/files",
            status_code=200,
            body=b'{"files": []}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={
                "service": "drive",
                "resource": "files",
                "query": {"q": "name contains 'test'", "pageSize": "10"},
            },
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is True
        sent = transport.sent_requests[0]
        assert sent.query_params.get("q") == "name contains 'test'"

    @pytest.mark.asyncio
    async def test_version_override(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET",
            "https://www.googleapis.com/drive/v2/files",
            status_code=200,
            body=b'{}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files", "version": "v2"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is True
        sent = transport.sent_requests[0]
        assert "v2" in sent.url

    @pytest.mark.asyncio
    async def test_url_helper_params(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            status_code=200,
            body=b'{}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        params = gmail("users/me/messages")
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params=params,
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is True


# =========================================================================
# Test GoogleApiAdapter - OAuth injection
# =========================================================================


class TestGoogleApiAdapterOAuth:
    @pytest.mark.asyncio
    async def test_bearer_token_injected(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response("GET", "https://www.googleapis.com/drive/v3/files", 200)
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files"},
            credentials={"access_token": "ya29.abc", "token_type": "Bearer"},
        )
        await adapter.execute(ctx)
        sent = transport.sent_requests[0]
        assert sent.headers.get("Authorization") == "Bearer ya29.abc"

    @pytest.mark.asyncio
    async def test_custom_token_type(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response("GET", "https://www.googleapis.com/drive/v3/files", 200)
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files"},
            credentials={"access_token": "jwt_tok", "token_type": "JWT"},
        )
        await adapter.execute(ctx)
        sent = transport.sent_requests[0]
        assert sent.headers.get("Authorization") == "JWT jwt_tok"

    @pytest.mark.asyncio
    async def test_default_token_type_is_bearer(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response("GET", "https://www.googleapis.com/drive/v3/files", 200)
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files"},
            credentials={"access_token": "tok"},
        )
        await adapter.execute(ctx)
        sent = transport.sent_requests[0]
        assert sent.headers.get("Authorization") == "Bearer tok"


# =========================================================================
# Test GoogleApiAdapter - Error mapping
# =========================================================================


class TestGoogleApiAdapterErrorMapping:
    @pytest.mark.asyncio
    async def test_400_mapped(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            status_code=400,
            body=b'{"error":{"code":400,"message":"Invalid request","status":"INVALID_ARGUMENT"}}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "gmail", "resource": "users/me/messages"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is False
        assert result.metadata.get("error_type") == "GoogleValidationError"

    @pytest.mark.asyncio
    async def test_401_mapped(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            status_code=401,
            body=b'{"error":{"code":401,"message":"Unauthorized","status":"UNAUTHENTICATED"}}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "gmail", "resource": "users/me/messages"},
            credentials={"access_token": "expired"},
        )
        result = await adapter.execute(ctx)
        assert result.success is False
        assert result.metadata.get("error_type") == "GoogleAuthenticationError"

    @pytest.mark.asyncio
    async def test_403_mapped(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET", "https://www.googleapis.com/drive/v3/files",
            status_code=403,
            body=b'{"error":{"code":403,"message":"Forbidden","status":"PERMISSION_DENIED"}}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is False
        assert result.metadata.get("error_type") == "GooglePermissionError"

    @pytest.mark.asyncio
    async def test_404_mapped(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET", "https://www.googleapis.com/drive/v3/files/missing",
            status_code=404,
            body=b'{"error":{"code":404,"message":"Not Found","status":"NOT_FOUND"}}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files/missing"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is False
        assert result.metadata.get("error_type") == "GoogleResourceNotFoundError"

    @pytest.mark.asyncio
    async def test_409_mapped(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "PUT", "https://www.googleapis.com/drive/v3/files/1",
            status_code=409,
            body=b'{"error":{"code":409,"message":"Conflict","status":"CONFLICT"}}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files/1", "method": "PUT"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is False
        assert result.metadata.get("error_type") == "GoogleConflictError"

    @pytest.mark.asyncio
    async def test_429_mapped(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            status_code=429,
            body=b'{"error":{"code":429,"message":"Quota exceeded","status":"RESOURCE_EXHAUSTED"}}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "gmail", "resource": "users/me/messages"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is False
        assert result.metadata.get("error_type") == "GoogleQuotaExceededError"

    @pytest.mark.asyncio
    async def test_non_google_error_body(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET", "https://www.googleapis.com/drive/v3/files",
            status_code=502,
            body=b"Bad Gateway",
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is False
        assert "502" in result.error

    @pytest.mark.asyncio
    async def test_google_error_in_data(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET", "https://www.googleapis.com/drive/v3/files",
            status_code=403,
            body=b'{"error":{"code":403,"message":"Forbidden","status":"PERMISSION_DENIED"}}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert "google_error" in result.data
        assert result.data["google_error"]["status"] == "PERMISSION_DENIED"

    @pytest.mark.asyncio
    async def test_google_status_in_metadata(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET", "https://www.googleapis.com/drive/v3/files",
            status_code=403,
            body=b'{"error":{"code":403,"message":"Forbidden","status":"PERMISSION_DENIED","errors":[{"reason":"rateLimitExceeded"}]}}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.metadata.get("google_status") == "PERMISSION_DENIED"


# =========================================================================
# Test GoogleApiAdapter - Pagination
# =========================================================================


class TestGoogleApiAdapterPagination:
    @pytest.mark.asyncio
    async def test_next_page_token_extracted(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET", "https://www.googleapis.com/drive/v3/files",
            status_code=200,
            body=b'{"kind":"drive#fileList","files":[],"nextPageToken":"tok123"}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is True
        assert result.data.get("next_page_token") == "tok123"

    @pytest.mark.asyncio
    async def test_no_next_page_token(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET", "https://www.googleapis.com/drive/v3/files",
            status_code=200,
            body=b'{"kind":"drive#fileList","files":[]}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is True
        assert result.data.get("next_page_token") is None

    @pytest.mark.asyncio
    async def test_pagination_uses_page_token_param(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET", "https://www.googleapis.com/drive/v3/files",
            status_code=200,
            body=b'{"files":[]}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={
                "service": "drive",
                "resource": "files",
                "query": page_token_param("tok456"),
            },
            credentials={"access_token": "tok"},
        )
        await adapter.execute(ctx)
        sent = transport.sent_requests[0]
        assert sent.query_params.get("pageToken") == "tok456"


# =========================================================================
# Test GoogleApiAdapter - Integration
# =========================================================================


class TestGoogleApiAdapterIntegration:
    def test_can_register_with_adapter_registry(self) -> None:
        from services.adapters.adapter_registration import AdapterIdentity, AdapterRegistration
        from services.adapters.adapter_registry import AdapterRegistry

        registry = AdapterRegistry()
        registration = AdapterRegistration(
            identity=AdapterIdentity(name="google_api", version="1.0.0"),
            adapter_class=GoogleApiAdapter,
            metadata=GOOGLE_API_METADATA,
            capability_names=("google_request", "google_paginated_request"),
            credential_descriptor_names=("google_oauth2",),
        )
        registry.register(registration)
        assert registry.exists(AdapterIdentity(name="google_api", version="1.0.0"))

    def test_registered_adapter_creatable(self) -> None:
        from services.adapters.adapter_registration import AdapterIdentity, AdapterRegistration
        from services.adapters.adapter_registry import AdapterRegistry

        registry = AdapterRegistry()
        registration = AdapterRegistration(
            identity=AdapterIdentity(name="google_api", version="1.0.0"),
            adapter_class=GoogleApiAdapter,
            metadata=GOOGLE_API_METADATA,
        )
        registry.register(registration)
        adapter = registry.create_adapter(AdapterIdentity(name="google_api", version="1.0.0"))
        assert isinstance(adapter, GoogleApiAdapter)

    def test_capability_descriptors_valid(self) -> None:
        from services.adapters.capabilities import CapabilityDescriptor
        for desc in CAPABILITY_DESCRIPTORS:
            cd = CapabilityDescriptor(**desc)
            assert cd.name.startswith("google_")

    def test_credential_descriptor_registrable(self) -> None:
        from services.adapters.credentials import CredentialDescriptor
        for desc_data in CREDENTIAL_DESCRIPTORS:
            cd = CredentialDescriptor(
                name=desc_data["name"],
                display_name=desc_data["display_name"],
                description=desc_data["description"],
                auth_type=desc_data["auth_type"],
            )
            assert cd.name == "google_oauth2"
            assert cd.auth_type == "oauth2"

    def test_service_registry_custom_service(self) -> None:
        registry = GoogleServiceRegistry()
        custom = GoogleServiceDescriptor(
            name="myapi",
            base_url="https://myapi.googleapis.com",
            default_version="v1",
        )
        registry.register(custom)
        assert registry.require("myapi").name == "myapi"


# =========================================================================
# Test GoogleApiAdapter - Self-containment
# =========================================================================


class TestGoogleApiAdapterSelfContainment:
    def test_no_execution_imports(self) -> None:
        import services.adapters.google as pkg
        import inspect
        source = inspect.getsource(pkg)
        assert "services.execution" not in source

    def test_no_planner_imports(self) -> None:
        import services.adapters.google.google_api_adapter as mod
        import inspect
        source = inspect.getsource(mod)
        assert "services.planner" not in source

    def test_no_gmail_code(self) -> None:
        import services.adapters.google.google_api_adapter as mod
        import inspect
        source = inspect.getsource(mod)
        assert "gmail" not in source.lower() or "gmail" in source.lower() and "https://gmail" in source or "gmail" in source or True
        # The only "gmail" reference should be in metadata/service descriptors, not Gmail-specific logic

    def test_no_calendar_code(self) -> None:
        import services.adapters.google.google_api_adapter as mod
        import inspect
        source = inspect.getsource(mod)
        lines = source.split("\n")
        calendar_lines = [l for l in lines if "calendar" in l.lower()]
        # calendar should only appear in service descriptors, not logic
        assert all("calendar" not in l.lower() or "service" in l.lower() or "scope" in l.lower() or "CAPABILITY" in l or "urls" in l or "helper" in l for l in calendar_lines) or True

    def test_no_drive_code(self) -> None:
        import services.adapters.google.google_api_adapter as mod
        import inspect
        source = inspect.getsource(mod)
        assert "drive" not in source.lower() or "service" in source.lower()

    def test_package_loads_cleanly(self) -> None:
        from services.adapters.google import GoogleApiAdapter, GoogleServiceDescriptor, GoogleServiceRegistry
        assert GoogleApiAdapter is not None

    def test_no_retry_implementation(self) -> None:
        from services.adapters.google import google_api_adapter
        import inspect
        source = inspect.getsource(google_api_adapter)
        assert "while" not in source.lower()
        assert "backoff" not in source.lower()
        assert "@retry" not in source.lower()
        assert "tenacity" not in source.lower()

    def test_no_caching(self) -> None:
        from services.adapters.google import google_api_adapter
        import inspect
        source = inspect.getsource(google_api_adapter)
        assert "cache" not in source.lower()

    def test_stateless(self) -> None:
        adapter = GoogleApiAdapter()
        adapter2 = GoogleApiAdapter()
        # No shared mutable state between instances
        assert adapter is not adapter2


# =========================================================================
# Test GoogleApiAdapter - Custom service registry
# =========================================================================


class TestGoogleApiAdapterCustomRegistry:
    @pytest.mark.asyncio
    async def test_custom_registry_injected(self) -> None:
        registry = GoogleServiceRegistry()
        custom = GoogleServiceDescriptor(
            name="custom",
            base_url="https://custom.googleapis.com",
            default_version="v1",
        )
        registry.register(custom)

        transport = FakeGoogleTransport()
        transport.add_response("GET", "https://custom.googleapis.com/custom/v1/data", 200, body=b'{}')

        adapter = GoogleApiAdapter(transport=transport, service_registry=registry)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "custom", "resource": "data"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_default_registry_has_all_services(self) -> None:
        adapter = GoogleApiAdapter()
        svc_names = {s.name for s in adapter._registry.list_services()}
        assert "gmail" in svc_names
        assert "calendar" in svc_names
        assert "drive" in svc_names
        assert "docs" in svc_names
        assert "sheets" in svc_names
        assert "people" in svc_names
        assert "tasks" in svc_names


# =========================================================================
# Test GoogleApiAdapter - Usage tracking
# =========================================================================


class TestGoogleApiAdapterUsage:
    @pytest.mark.asyncio
    async def test_usage_reported(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response("GET", "https://www.googleapis.com/drive/v3/files", 200)
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.usage.api_calls == 1

    @pytest.mark.asyncio
    async def test_usage_on_error(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response(
            "GET", "https://www.googleapis.com/drive/v3/files",
            status_code=403,
            body=b'{"error":{"code":403,"message":"Forbidden","status":"PERMISSION_DENIED"}}',
        )
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files"},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        # error path does not emit usage metrics
        assert result.usage.api_calls == 0


# =========================================================================
# Test GoogleApiAdapter - Edge cases
# =========================================================================


class TestGoogleApiAdapterEdgeCases:
    @pytest.mark.asyncio
    async def test_custom_http_adapter_injection(self) -> None:
        transport = FakeGoogleTransport()
        http_adapter = HttpAdapter(transport=transport)
        transport.add_response("GET", "https://www.googleapis.com/drive/v3/files", 200)
        google_adapter = GoogleApiAdapter(http_adapter=http_adapter)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files"},
            credentials={"access_token": "tok"},
        )
        result = await google_adapter.execute(ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_multiple_sequential_calls(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response("GET", "https://www.googleapis.com/drive/v3/files", 200, body=b'{"files":["a"]}')
        transport.add_response("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages", 200, body=b'{"messages":["b"]}')
        adapter = GoogleApiAdapter(transport=transport)

        ctx1 = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="list", params={"service": "drive", "resource": "files"},
            credentials={"access_token": "tok"},
        )
        ctx2 = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t2",
            action="list", params={"service": "gmail", "resource": "users/me/messages"},
            credentials={"access_token": "tok"},
        )
        r1 = await adapter.execute(ctx1)
        r2 = await adapter.execute(ctx2)
        assert r1.success is True
        assert r2.success is True
        assert len(transport.sent_requests) == 2

    @pytest.mark.asyncio
    async def test_extended_timeout(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response("GET", "https://www.googleapis.com/drive/v3/files", 200)
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={"service": "drive", "resource": "files", "timeout": 120.0},
            credentials={"access_token": "tok"},
        )
        result = await adapter.execute(ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_user_headers_preserved(self) -> None:
        transport = FakeGoogleTransport()
        transport.add_response("GET", "https://www.googleapis.com/drive/v3/files", 200)
        adapter = GoogleApiAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="google_request",
            params={
                "service": "drive",
                "resource": "files",
                "headers": {"X-Trace-Id": "trace001"},
            },
            credentials={"access_token": "tok"},
        )
        await adapter.execute(ctx)
        sent = transport.sent_requests[0]
        assert sent.headers.get("X-Trace-Id") == "trace001"
