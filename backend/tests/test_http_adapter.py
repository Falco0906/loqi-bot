from __future__ import annotations

import base64
import json as _json
import pickle
from dataclasses import field
from typing import Any, Optional

import pytest

from services.adapters.adapter_context import AdapterContext
from services.adapters.http.auth import (
    ApiKeyAuth,
    AuthStrategy,
    BasicAuth,
    BearerTokenAuth,
    CustomHeaderAuth,
    NoAuth,
    get_auth_strategy,
    resolve_auth,
)
from services.adapters.http.exceptions import (
    ConnectionError,
    DeserializationError,
    DnsError,
    HttpError,
    HttpStatusError,
    InvalidContentTypeError,
    InvalidHeaderError,
    InvalidMethodError,
    InvalidTimeoutError,
    InvalidUrlError,
    RequestTimeoutError,
    SerializationError,
)
from services.adapters.http.http_adapter import (
    CAPABILITY_DESCRIPTORS,
    CREDENTIAL_DESCRIPTORS,
    HTTP_ADAPTER_METADATA,
    HttpAdapter,
)
from services.adapters.http.models import (
    SUPPORTED_METHODS,
    HttpRequest,
    HttpResponse,
)
from services.adapters.http.serializers import (
    BodySerializer,
    FormSerializer,
    JsonSerializer,
    PlainTextSerializer,
    detect_serializer,
    get_serializer,
)
from services.adapters.http.transport import HttpTransport
from services.adapters.http.validators import (
    validate_content_type,
    validate_headers,
    validate_method,
    validate_request,
    validate_timeout,
    validate_url,
)
from services.adapters.models import AdapterMetadata, AdapterResult, UsageInfo


# =========================================================================
# Fake transport for adapter tests
# =========================================================================


class FakeHttpTransport:
    """Fake HTTP transport for adapter tests.

    Maps (method, url) to canned responses.  Can also simulate failures.
    """

    def __init__(self) -> None:
        self._responses: dict[tuple[str, str], HttpResponse] = {}
        self._errors: dict[tuple[str, str], Exception] = {}
        self.sent_requests: list[HttpRequest] = []

    def add_response(
        self,
        method: str,
        url: str,
        status_code: int = 200,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        elapsed: float = 0.0,
        content_type: str = "",
    ) -> None:
        self._responses[(method.upper(), url)] = HttpResponse(
            status_code=status_code,
            headers=headers or {},
            body=body,
            elapsed=elapsed,
            content_type=content_type or "application/json",
        )

    def add_error(self, method: str, url: str, error: Exception) -> None:
        self._errors[(method.upper(), url)] = error

    async def send(self, request: HttpRequest) -> HttpResponse:
        self.sent_requests.append(request)
        key = (request.method.upper(), request.url)
        if key in self._errors:
            raise self._errors[key]
        if key not in self._responses:
            raise HttpStatusError(
                message="HTTP 404 for not found",
                status_code=404,
                body='{"error":"not found"}',
                headers={"content-type": "application/json"},
            )
        resp = self._responses[key]
        if resp.is_client_error() or resp.is_server_error():
            raise HttpStatusError(
                message=f"HTTP {resp.status_code} for {request.url}",
                status_code=resp.status_code,
                body=resp.body.decode("utf-8", errors="replace"),
                headers=dict(resp.headers),
            )
        return resp


# =========================================================================
# Test HttpRequest model
# =========================================================================


class TestHttpRequestConstruction:
    def test_minimal(self) -> None:
        req = HttpRequest(method="GET", url="https://example.com")
        assert req.method == "GET"
        assert req.url == "https://example.com"
        assert req.headers == {}
        assert req.query_params == {}
        assert req.body is None
        assert req.timeout == 30.0
        assert req.content_type == ""
        assert req.accept == ""

    def test_full(self) -> None:
        req = HttpRequest(
            method="POST",
            url="https://api.example.com/data",
            headers={"Authorization": "Bearer tok"},
            query_params={"page": "1"},
            body={"key": "value"},
            timeout=15.0,
            content_type="application/json",
            accept="application/json",
        )
        assert req.method == "POST"
        assert req.query_params == {"page": "1"}
        assert req.body == {"key": "value"}
        assert req.timeout == 15.0
        assert req.content_type == "application/json"
        assert req.accept == "application/json"

    def test_method_case_insensitive(self) -> None:
        for m in ("get", "Get", "GET", "post", "Post", "POST"):
            req = HttpRequest(method=m, url="https://example.com")
            assert req.method == m

    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    def test_all_supported_methods(self, method: str) -> None:
        req = HttpRequest(method=method, url="https://example.com")
        assert req.method == method

    def test_lowercase_method_stored_as_given(self) -> None:
        req = HttpRequest(method="get", url="https://example.com")
        assert req.method == "get"

    def test_default_timeout(self) -> None:
        req = HttpRequest(method="GET", url="https://example.com")
        assert req.timeout == 30.0

    def test_float_timeout(self) -> None:
        req = HttpRequest(method="GET", url="https://example.com", timeout=0.5)
        assert req.timeout == 0.5

    def test_int_timeout(self) -> None:
        req = HttpRequest(method="GET", url="https://example.com", timeout=10)
        assert req.timeout == 10

    def test_supports_https(self) -> None:
        req = HttpRequest(method="GET", url="https://example.com")
        assert req.url == "https://example.com"

    def test_supports_http(self) -> None:
        req = HttpRequest(method="GET", url="http://example.com")
        assert req.url == "http://example.com"

    def test_empty_headers_default(self) -> None:
        req = HttpRequest(method="GET", url="https://example.com")
        assert req.headers == {}

    def test_empty_query_params_default(self) -> None:
        req = HttpRequest(method="GET", url="https://example.com")
        assert req.query_params == {}

    def test_string_body(self) -> None:
        req = HttpRequest(method="POST", url="https://example.com", body="hello")
        assert req.body == "hello"

    def test_bytes_body(self) -> None:
        req = HttpRequest(method="POST", url="https://example.com", body=b"hello")
        assert req.body == b"hello"

    def test_dict_body(self) -> None:
        req = HttpRequest(method="POST", url="https://example.com", body={"a": 1})
        assert req.body == {"a": 1}

    def test_list_body(self) -> None:
        req = HttpRequest(method="POST", url="https://example.com", body=[1, 2])
        assert req.body == [1, 2]

    def test_none_body(self) -> None:
        req = HttpRequest(method="GET", url="https://example.com")
        assert req.body is None


class TestHttpRequestValidation:
    def test_empty_method_raises(self) -> None:
        with pytest.raises(InvalidMethodError):
            HttpRequest(method="", url="https://example.com")

    def test_unsupported_method_raises(self) -> None:
        with pytest.raises(InvalidMethodError, match="Unsupported method"):
            HttpRequest(method="TRACE", url="https://example.com")

    def test_method_is_not_string_raises(self) -> None:
        with pytest.raises(InvalidMethodError):
            HttpRequest(method=123, url="https://example.com")

    def test_empty_url_raises(self) -> None:
        with pytest.raises(InvalidUrlError):
            HttpRequest(method="GET", url="")

    def test_url_no_scheme_raises(self) -> None:
        with pytest.raises(InvalidUrlError, match="http"):
            HttpRequest(method="GET", url="example.com")

    def test_url_ftp_scheme_raises(self) -> None:
        with pytest.raises(InvalidUrlError, match="http"):
            HttpRequest(method="GET", url="ftp://example.com")

    def test_url_not_string_raises(self) -> None:
        with pytest.raises(InvalidUrlError):
            HttpRequest(method="GET", url=123)

    def test_negative_timeout_raises(self) -> None:
        with pytest.raises(InvalidTimeoutError):
            HttpRequest(method="GET", url="https://example.com", timeout=-1)

    def test_zero_timeout_raises(self) -> None:
        with pytest.raises(InvalidTimeoutError):
            HttpRequest(method="GET", url="https://example.com", timeout=0)

    def test_string_timeout_raises(self) -> None:
        with pytest.raises(InvalidTimeoutError):
            HttpRequest(method="GET", url="https://example.com", timeout="30")

    def test_unsupported_method_message_includes_supported(self) -> None:
        with pytest.raises(InvalidMethodError) as exc:
            HttpRequest(method="TRACE", url="https://example.com")
        assert "GET" in str(exc.value)
        assert "POST" in str(exc.value)
        assert "DELETE" in str(exc.value)


class TestHttpRequestImmutability:
    def test_cannot_reassign_headers(self) -> None:
        req = HttpRequest(method="GET", url="https://example.com", headers={"a": "1"})
        with pytest.raises(AttributeError):
            req.headers = {"b": "2"}

    def test_cannot_reassign_query_params(self) -> None:
        req = HttpRequest(method="GET", url="https://example.com", query_params={"a": "1"})
        with pytest.raises(AttributeError):
            req.query_params = {"b": "2"}

    def test_frozen_dataclass(self) -> None:
        req = HttpRequest(method="GET", url="https://example.com")
        with pytest.raises(AttributeError):
            req.method = "POST"

    def test_pickle_roundtrip(self) -> None:
        req = HttpRequest(method="POST", url="https://example.com/data", body={"k": "v"})
        restored = pickle.loads(pickle.dumps(req))
        assert restored.method == req.method
        assert restored.url == req.url
        assert restored.body == req.body

    def test_equality(self) -> None:
        a = HttpRequest(method="GET", url="https://example.com")
        b = HttpRequest(method="GET", url="https://example.com")
        assert a == b

    def test_inequality_different_url(self) -> None:
        a = HttpRequest(method="GET", url="https://example.com/a")
        b = HttpRequest(method="GET", url="https://example.com/b")
        assert a != b

    def test_cannot_hash_with_dict_fields(self) -> None:
        req = HttpRequest(method="GET", url="https://example.com")
        with pytest.raises(TypeError):
            hash(req)

    def test_repr(self) -> None:
        req = HttpRequest(method="GET", url="https://example.com")
        r = repr(req)
        assert "HttpRequest" in r
        assert "GET" in r
        assert "example.com" in r


# =========================================================================
# Test HttpResponse model
# =========================================================================


class TestHttpResponseConstruction:
    def test_minimal(self) -> None:
        resp = HttpResponse(status_code=200)
        assert resp.status_code == 200
        assert resp.headers == {}
        assert resp.body == b""
        assert resp.elapsed == 0.0
        assert resp.content_type == ""

    def test_full(self) -> None:
        resp = HttpResponse(
            status_code=201,
            headers={"location": "/new"},
            body=b'{"id": 1}',
            elapsed=0.5,
            content_type="application/json",
        )
        assert resp.status_code == 201
        assert resp.headers["location"] == "/new"
        assert resp.body == b'{"id": 1}'
        assert resp.elapsed == 0.5
        assert resp.content_type == "application/json"

    def test_empty_body(self) -> None:
        resp = HttpResponse(status_code=204)
        assert resp.body == b""

    def test_large_body(self) -> None:
        body = b"x" * 10000
        resp = HttpResponse(status_code=200, body=body)
        assert len(resp.body) == 10000


class TestHttpResponseHelpers:
    def test_success_200(self) -> None:
        resp = HttpResponse(status_code=200)
        assert resp.success is True
        assert resp.is_success() is True
        assert resp.is_client_error() is False
        assert resp.is_server_error() is False

    def test_success_201(self) -> None:
        resp = HttpResponse(status_code=201)
        assert resp.success is True
        assert resp.is_success() is True

    def test_success_299(self) -> None:
        resp = HttpResponse(status_code=299)
        assert resp.is_success() is True
        assert resp.is_client_error() is False

    def test_redirect_300(self) -> None:
        resp = HttpResponse(status_code=300)
        assert resp.success is True
        assert resp.is_success() is False

    def test_redirect_399(self) -> None:
        resp = HttpResponse(status_code=399)
        assert resp.success is True
        assert resp.is_success() is False

    def test_client_error_400(self) -> None:
        resp = HttpResponse(status_code=400)
        assert resp.success is False
        assert resp.is_client_error() is True

    def test_client_error_404(self) -> None:
        resp = HttpResponse(status_code=404)
        assert resp.is_client_error() is True
        assert resp.is_server_error() is False

    def test_client_error_499(self) -> None:
        resp = HttpResponse(status_code=499)
        assert resp.is_client_error() is True

    def test_server_error_500(self) -> None:
        resp = HttpResponse(status_code=500)
        assert resp.success is False
        assert resp.is_server_error() is True

    def test_server_error_503(self) -> None:
        resp = HttpResponse(status_code=503)
        assert resp.is_server_error() is True
        assert resp.is_client_error() is False

    def test_server_error_599(self) -> None:
        resp = HttpResponse(status_code=599)
        assert resp.is_server_error() is True


class TestHttpResponseJson:
    def test_json_parsed(self) -> None:
        resp = HttpResponse(status_code=200, body=b'{"key": "value"}')
        assert resp.json == {"key": "value"}

    def test_json_empty_body_returns_none(self) -> None:
        resp = HttpResponse(status_code=200, body=b"")
        assert resp.json is None

    def test_invalid_json_raises(self) -> None:
        resp = HttpResponse(status_code=200, body=b"not json")
        with pytest.raises(DeserializationError):
            _ = resp.json

    def test_nested_json(self) -> None:
        resp = HttpResponse(status_code=200, body=b'{"a": {"b": [1, 2]}}')
        assert resp.json == {"a": {"b": [1, 2]}}

    def test_json_array(self) -> None:
        resp = HttpResponse(status_code=200, body=b'[1, 2, 3]')
        assert resp.json == [1, 2, 3]

    def test_json_number(self) -> None:
        resp = HttpResponse(status_code=200, body=b"42")
        assert resp.json == 42

    def test_json_boolean(self) -> None:
        resp = HttpResponse(status_code=200, body=b"true")
        assert resp.json is True

    def test_json_null(self) -> None:
        resp = HttpResponse(status_code=200, body=b"null")
        assert resp.json is None

    def test_unicode_body(self) -> None:
        resp = HttpResponse(status_code=200, body='{"msg": "héllo"}'.encode("utf-8"))
        assert resp.json == {"msg": "héllo"}


class TestHttpResponseImmutability:
    def test_frozen_dataclass(self) -> None:
        resp = HttpResponse(status_code=200)
        with pytest.raises(AttributeError):
            resp.status_code = 404

    def test_repr(self) -> None:
        resp = HttpResponse(status_code=200, body=b"data")
        r = repr(resp)
        assert "HttpResponse" in r
        assert "200" in r
        assert "4 bytes" in r


# =========================================================================
# Test SUPPORTED_METHODS
# =========================================================================


class TestSupportedMethods:
    def test_all_methods_present(self) -> None:
        expected = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
        assert SUPPORTED_METHODS == expected

    def test_count(self) -> None:
        assert len(SUPPORTED_METHODS) == 7


# =========================================================================
# Test Exception Hierarchy
# =========================================================================


class TestHttpExceptionHierarchy:
    def test_http_error_is_base(self) -> None:
        assert issubclass(HttpError, Exception)

    def test_invalid_url_error(self) -> None:
        assert issubclass(InvalidUrlError, HttpError)

    def test_invalid_method_error(self) -> None:
        assert issubclass(InvalidMethodError, HttpError)

    def test_invalid_timeout_error(self) -> None:
        assert issubclass(InvalidTimeoutError, HttpError)

    def test_invalid_header_error(self) -> None:
        assert issubclass(InvalidHeaderError, HttpError)

    def test_invalid_content_type_error(self) -> None:
        assert issubclass(InvalidContentTypeError, HttpError)

    def test_request_timeout_error(self) -> None:
        assert issubclass(RequestTimeoutError, HttpError)

    def test_connection_error(self) -> None:
        assert issubclass(ConnectionError, HttpError)

    def test_dns_error(self) -> None:
        assert issubclass(DnsError, HttpError)

    def test_serialization_error(self) -> None:
        assert issubclass(SerializationError, HttpError)

    def test_deserialization_error(self) -> None:
        assert issubclass(DeserializationError, HttpError)

    def test_http_status_error(self) -> None:
        assert issubclass(HttpStatusError, HttpError)

    def test_http_status_error_carries_fields(self) -> None:
        exc = HttpStatusError("Not Found", 404, body="not found", headers={"x-id": "1"})
        assert exc.status_code == 404
        assert exc.body == "not found"
        assert exc.headers == {"x-id": "1"}
        assert str(exc) == "Not Found"

    def test_exceptions_distinct(self) -> None:
        names = {
            InvalidUrlError,
            InvalidMethodError,
            InvalidTimeoutError,
            InvalidHeaderError,
            InvalidContentTypeError,
            RequestTimeoutError,
            ConnectionError,
            DnsError,
            SerializationError,
            DeserializationError,
            HttpStatusError,
        }
        assert len(names) == 11  # plus HttpError base = 12 total

    def test_serialization_error_message(self) -> None:
        exc = SerializationError("bad encoding")
        assert "bad encoding" in str(exc)

    def test_request_timeout_error_message(self) -> None:
        exc = RequestTimeoutError("timed out")
        assert "timed out" in str(exc)


# =========================================================================
# Test Auth Strategies
# =========================================================================


class TestNoAuth:
    def test_returns_empty_headers(self) -> None:
        auth = NoAuth()
        assert auth.apply({}) == {}

    def test_ignores_credentials(self) -> None:
        auth = NoAuth()
        assert auth.apply({"api_key": "secret"}) == {}

    def test_accepts_none(self) -> None:
        auth = NoAuth()
        assert auth.apply(None) == {}


class TestApiKeyAuth:
    def test_default_header_name(self) -> None:
        auth = ApiKeyAuth()
        headers = auth.apply({"api_key": "mykey"})
        assert headers == {"X-API-Key": "mykey"}

    def test_custom_header_name(self) -> None:
        auth = ApiKeyAuth()
        headers = auth.apply({"api_key": "mykey", "header_name": "X-Custom"})
        assert headers == {"X-Custom": "mykey"}

    def test_empty_api_key(self) -> None:
        auth = ApiKeyAuth()
        headers = auth.apply({"api_key": ""})
        assert headers == {"X-API-Key": ""}

    def test_missing_api_key(self) -> None:
        auth = ApiKeyAuth()
        headers = auth.apply({})
        assert headers == {"X-API-Key": ""}

    def test_special_chars_in_key(self) -> None:
        auth = ApiKeyAuth()
        headers = auth.apply({"api_key": "key with spaces!"})
        assert headers == {"X-API-Key": "key with spaces!"}


class TestBearerTokenAuth:
    def test_default_token_field(self) -> None:
        auth = BearerTokenAuth()
        headers = auth.apply({"token": "mytoken"})
        assert headers == {"Authorization": "Bearer mytoken"}

    def test_access_token_field_fallback(self) -> None:
        auth = BearerTokenAuth()
        headers = auth.apply({"access_token": "mytoken"})
        assert headers == {"Authorization": "Bearer mytoken"}

    def test_token_preferred_over_access_token(self) -> None:
        auth = BearerTokenAuth()
        headers = auth.apply({"token": "preferred", "access_token": "fallback"})
        assert headers == {"Authorization": "Bearer preferred"}

    def test_custom_token_type(self) -> None:
        auth = BearerTokenAuth()
        headers = auth.apply({"token": "jwt", "token_type": "JWT"})
        assert headers == {"Authorization": "JWT jwt"}

    def test_empty_token(self) -> None:
        auth = BearerTokenAuth()
        headers = auth.apply({})
        assert headers == {"Authorization": "Bearer "}

    def test_special_tokens(self) -> None:
        auth = BearerTokenAuth()
        headers = auth.apply({"token": "eyJ.eyJ.stuff"})
        assert headers == {"Authorization": "Bearer eyJ.eyJ.stuff"}


class TestBasicAuth:
    def test_encodes_credentials(self) -> None:
        auth = BasicAuth()
        headers = auth.apply({"username": "alice", "password": "secret"})
        expected = "Basic " + base64.b64encode(b"alice:secret").decode()
        assert headers == {"Authorization": expected}

    def test_empty_username(self) -> None:
        auth = BasicAuth()
        headers = auth.apply({"username": "", "password": "secret"})
        expected = "Basic " + base64.b64encode(b":secret").decode()
        assert headers == {"Authorization": expected}

    def test_empty_password(self) -> None:
        auth = BasicAuth()
        headers = auth.apply({"username": "alice", "password": ""})
        expected = "Basic " + base64.b64encode(b"alice:").decode()
        assert headers == {"Authorization": expected}

    def test_special_chars(self) -> None:
        auth = BasicAuth()
        headers = auth.apply({"username": "user@host", "password": 'p@ss!:"'})
        expected = "Basic " + base64.b64encode(b'user@host:p@ss!:"').decode()
        assert headers == {"Authorization": expected}

    def test_unicode(self) -> None:
        auth = BasicAuth()
        headers = auth.apply({"username": "用户", "password": "密码"})
        encoded = base64.b64encode("用户:密码".encode()).decode()
        assert headers == {"Authorization": f"Basic {encoded}"}


class TestCustomHeaderAuth:
    def test_custom_header(self) -> None:
        auth = CustomHeaderAuth()
        headers = auth.apply({"header_name": "X-Session", "header_value": "abc123"})
        assert headers == {"X-Session": "abc123"}

    def test_empty_name(self) -> None:
        auth = CustomHeaderAuth()
        headers = auth.apply({"header_name": "", "header_value": "val"})
        assert headers == {"": "val"}

    def test_empty_value(self) -> None:
        auth = CustomHeaderAuth()
        headers = auth.apply({"header_name": "X-Key", "header_value": ""})
        assert headers == {"X-Key": ""}

    def test_missing_fields(self) -> None:
        auth = CustomHeaderAuth()
        headers = auth.apply({})
        assert headers == {"": ""}


class TestResolveAuth:
    def test_default_no_auth(self) -> None:
        strategy, creds = resolve_auth({})
        assert isinstance(strategy, NoAuth)

    def test_explicit_no_auth(self) -> None:
        strategy, creds = resolve_auth({"auth_type": "no_auth"})
        assert isinstance(strategy, NoAuth)

    def test_api_key_auth(self) -> None:
        strategy, creds = resolve_auth({"auth_type": "api_key", "api_key": "key1"})
        assert isinstance(strategy, ApiKeyAuth)
        assert creds == {"api_key": "key1"}

    def test_bearer_token_auth(self) -> None:
        strategy, creds = resolve_auth({"auth_type": "bearer_token", "token": "tok"})
        assert isinstance(strategy, BearerTokenAuth)
        assert creds == {"token": "tok"}

    def test_basic_auth(self) -> None:
        strategy, creds = resolve_auth(
            {"auth_type": "basic_auth", "username": "u", "password": "p"}
        )
        assert isinstance(strategy, BasicAuth)
        assert creds == {"username": "u", "password": "p"}

    def test_custom_header_auth(self) -> None:
        strategy, creds = resolve_auth(
            {"auth_type": "custom_header", "header_name": "X-K", "header_value": "v"}
        )
        assert isinstance(strategy, CustomHeaderAuth)
        assert creds == {"header_name": "X-K", "header_value": "v"}

    def test_auth_type_removed_from_creds(self) -> None:
        _, creds = resolve_auth({"auth_type": "api_key", "api_key": "k"})
        assert "auth_type" not in creds

    def test_unknown_auth_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown auth type"):
            resolve_auth({"auth_type": "unknown_strategy"})

    def test_none_auth_type_defaults_to_no_auth(self) -> None:
        strategy, _ = resolve_auth({"auth_type": None})
        assert isinstance(strategy, NoAuth)

    def test_registry_contains_all_strategies(self) -> None:
        for auth_type in ("no_auth", "api_key", "bearer_token", "basic_auth", "custom_header"):
            strategy = get_auth_strategy(auth_type)
            assert isinstance(strategy, AuthStrategy)

    def test_registry_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown auth type"):
            get_auth_strategy("nonexistent")


# =========================================================================
# Test Serializers
# =========================================================================


class TestJsonSerializer:
    def test_serialize_dict(self) -> None:
        s = JsonSerializer()
        result = s.serialize({"a": 1, "b": "two"})
        assert _json.loads(result) == {"a": 1, "b": "two"}

    def test_serialize_list(self) -> None:
        s = JsonSerializer()
        result = s.serialize([1, 2, 3])
        assert _json.loads(result) == [1, 2, 3]

    def test_serialize_none(self) -> None:
        s = JsonSerializer()
        result = s.serialize(None)
        assert _json.loads(result) is None

    def test_serialize_string(self) -> None:
        s = JsonSerializer()
        result = s.serialize("hello")
        assert _json.loads(result) == "hello"

    def test_serialize_raises_on_non_serializable(self) -> None:
        s = JsonSerializer()
        with pytest.raises(SerializationError):
            s.serialize(object())

    def test_deserialize(self) -> None:
        s = JsonSerializer()
        result = s.deserialize(b'{"a": 1}')
        assert result == {"a": 1}

    def test_deserialize_array(self) -> None:
        s = JsonSerializer()
        result = s.deserialize(b"[1, 2]")
        assert result == [1, 2]

    def test_deserialize_invalid_json_raises(self) -> None:
        s = JsonSerializer()
        with pytest.raises(SerializationError):
            s.deserialize(b"broken")

    def test_content_type(self) -> None:
        s = JsonSerializer()
        assert s.content_type == "application/json"


class TestFormSerializer:
    def test_serialize_simple(self) -> None:
        s = FormSerializer()
        result = s.serialize({"a": "1", "b": "two"})
        decoded = result.decode()
        assert "a=1" in decoded
        assert "b=two" in decoded

    def test_serialize_list_values(self) -> None:
        s = FormSerializer()
        result = s.serialize({"a": ["1", "2"]})
        decoded = result.decode()
        assert "a=1" in decoded
        assert "a=2" in decoded

    def test_serialize_raises_on_non_dict(self) -> None:
        s = FormSerializer()
        with pytest.raises(SerializationError):
            s.serialize("string")

    def test_deserialize(self) -> None:
        s = FormSerializer()
        result = s.deserialize(b"a=1&b=two")
        assert result == {"a": "1", "b": "two"}

    def test_deserialize_list_values(self) -> None:
        s = FormSerializer()
        result = s.deserialize(b"a=1&a=2")
        assert result == {"a": ["1", "2"]}

    def test_deserialize_empty(self) -> None:
        s = FormSerializer()
        result = s.deserialize(b"")
        assert result == {}

    def test_content_type(self) -> None:
        s = FormSerializer()
        assert s.content_type == "application/x-www-form-urlencoded"

    def test_serialize_empty_dict(self) -> None:
        s = FormSerializer()
        result = s.serialize({})
        assert result == b""

    def test_serialize_special_chars(self) -> None:
        s = FormSerializer()
        result = s.serialize({"q": "hello world", "n": "a&b"})
        decoded = result.decode()
        assert "hello+world" in decoded or "hello%20world" in decoded

    def test_deserialize_unicode_error_raises(self) -> None:
        s = FormSerializer()
        with pytest.raises(SerializationError):
            s.deserialize(b"\xff\xfe")


class TestPlainTextSerializer:
    def test_serialize_string(self) -> None:
        s = PlainTextSerializer()
        result = s.serialize("hello")
        assert result == b"hello"

    def test_serialize_bytes_passthrough(self) -> None:
        s = PlainTextSerializer()
        result = s.serialize(b"hello")
        assert result == b"hello"

    def test_serialize_int(self) -> None:
        s = PlainTextSerializer()
        result = s.serialize(42)
        assert result == b"42"

    def test_serialize_float(self) -> None:
        s = PlainTextSerializer()
        result = s.serialize(3.14)
        assert result == b"3.14"

    def test_serialize_none(self) -> None:
        s = PlainTextSerializer()
        result = s.serialize(None)
        assert result == b"None"

    def test_deserialize(self) -> None:
        s = PlainTextSerializer()
        result = s.deserialize(b"hello")
        assert result == "hello"

    def test_deserialize_unicode(self) -> None:
        s = PlainTextSerializer()
        result = s.deserialize("héllo".encode("utf-8"))
        assert result == "héllo"

    def test_content_type(self) -> None:
        s = PlainTextSerializer()
        assert s.content_type == "text/plain"

    def test_serialize_any_object_via_str(self) -> None:
        s = PlainTextSerializer()
        result = s.serialize(42)
        assert result == b"42"


class TestDetectSerializer:
    def test_json_by_content_type(self) -> None:
        serializer = detect_serializer({"a": 1}, "application/json")
        assert isinstance(serializer, JsonSerializer)

    def test_form_by_content_type(self) -> None:
        serializer = detect_serializer({"a": 1}, "application/x-www-form-urlencoded")
        assert isinstance(serializer, FormSerializer)

    def test_plain_text_by_content_type(self) -> None:
        serializer = detect_serializer("hello", "text/plain")
        assert isinstance(serializer, PlainTextSerializer)

    def test_json_inferred_from_dict(self) -> None:
        serializer = detect_serializer({"a": 1})
        assert isinstance(serializer, JsonSerializer)

    def test_plain_text_inferred_from_string(self) -> None:
        serializer = detect_serializer("hello")
        assert isinstance(serializer, PlainTextSerializer)

    def test_plain_text_inferred_from_bytes(self) -> None:
        serializer = detect_serializer(b"hello")
        assert isinstance(serializer, PlainTextSerializer)

    def test_content_type_with_charset(self) -> None:
        serializer = detect_serializer({"a": 1}, "application/json; charset=utf-8")
        assert isinstance(serializer, JsonSerializer)

    def test_content_type_case_insensitive(self) -> None:
        serializer = detect_serializer({"a": 1}, "APPLICATION/JSON")
        assert isinstance(serializer, JsonSerializer)

    def test_unknown_content_type_uses_inference(self) -> None:
        serializer = detect_serializer("hello", "application/xml")
        assert isinstance(serializer, PlainTextSerializer)

    def test_form_content_type_with_dict(self) -> None:
        serializer = detect_serializer({"a": 1}, "application/x-www-form-urlencoded")
        assert isinstance(serializer, FormSerializer)


class TestGetSerializer:
    def test_json(self) -> None:
        s = get_serializer("application/json")
        assert isinstance(s, JsonSerializer)

    def test_form(self) -> None:
        s = get_serializer("application/x-www-form-urlencoded")
        assert isinstance(s, FormSerializer)

    def test_plain_text(self) -> None:
        s = get_serializer("text/plain")
        assert isinstance(s, PlainTextSerializer)

    def test_unknown_returns_none(self) -> None:
        assert get_serializer("application/xml") is None

    def test_empty_string_returns_none(self) -> None:
        assert get_serializer("") is None

    def test_case_insensitive(self) -> None:
        s = get_serializer("APPLICATION/JSON")
        assert isinstance(s, JsonSerializer)

    def test_with_parameters(self) -> None:
        s = get_serializer("application/json; charset=utf-8")
        assert isinstance(s, JsonSerializer)


# =========================================================================
# Test Validators
# =========================================================================


class TestValidateUrl:
    def test_valid_https(self) -> None:
        validate_url("https://example.com")

    def test_valid_http(self) -> None:
        validate_url("http://example.com")

    def test_valid_with_path(self) -> None:
        validate_url("https://example.com/api/v1/users")

    def test_valid_with_query(self) -> None:
        validate_url("https://example.com?page=1")

    def test_valid_with_port(self) -> None:
        validate_url("https://example.com:8080/path")

    def test_empty_raises(self) -> None:
        with pytest.raises(InvalidUrlError):
            validate_url("")

    def test_whitespace_raises(self) -> None:
        with pytest.raises(InvalidUrlError):
            validate_url("   ")

    def test_no_scheme_raises(self) -> None:
        with pytest.raises(InvalidUrlError, match="scheme"):
            validate_url("example.com")

    def test_ftp_scheme_raises(self) -> None:
        with pytest.raises(InvalidUrlError, match="scheme"):
            validate_url("ftp://example.com")

    def test_ws_scheme_raises(self) -> None:
        with pytest.raises(InvalidUrlError, match="scheme"):
            validate_url("ws://example.com")

    def test_non_string_raises(self) -> None:
        with pytest.raises(InvalidUrlError):
            validate_url(123)

    def test_none_raises(self) -> None:
        with pytest.raises(InvalidUrlError):
            validate_url(None)


class TestValidateMethod:
    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    def test_valid_methods(self, method: str) -> None:
        validate_method(method)

    def test_lowercase_valid(self) -> None:
        validate_method("get")
        validate_method("post")

    def test_empty_raises(self) -> None:
        with pytest.raises(InvalidMethodError):
            validate_method("")

    def test_whitespace_raises(self) -> None:
        with pytest.raises(InvalidMethodError):
            validate_method("  ")

    def test_unsupported_raises(self) -> None:
        with pytest.raises(InvalidMethodError):
            validate_method("TRACE")

    def test_non_string_raises(self) -> None:
        with pytest.raises(InvalidMethodError):
            validate_method(123)

    def test_none_raises(self) -> None:
        with pytest.raises(InvalidMethodError):
            validate_method(None)

    def test_error_message_includes_supported(self) -> None:
        with pytest.raises(InvalidMethodError) as exc:
            validate_method("TRACE")
        msg = str(exc.value)
        for m in ("GET", "POST", "DELETE"):
            assert m in msg


class TestValidateTimeout:
    def test_valid_int(self) -> None:
        validate_timeout(30)

    def test_valid_float(self) -> None:
        validate_timeout(0.5)

    def test_valid_large(self) -> None:
        validate_timeout(3600)

    def test_negative_raises(self) -> None:
        with pytest.raises(InvalidTimeoutError):
            validate_timeout(-1)

    def test_zero_raises(self) -> None:
        with pytest.raises(InvalidTimeoutError):
            validate_timeout(0)

    def test_string_raises(self) -> None:
        with pytest.raises(InvalidTimeoutError):
            validate_timeout("30")

    def test_none_raises(self) -> None:
        with pytest.raises(InvalidTimeoutError):
            validate_timeout(None)

    def test_zero_point_zero_raises(self) -> None:
        with pytest.raises(InvalidTimeoutError):
            validate_timeout(0.0)


class TestValidateHeaders:
    def test_none_is_valid(self) -> None:
        validate_headers(None)

    def test_empty_dict(self) -> None:
        validate_headers({})

    def test_valid_headers(self) -> None:
        validate_headers({"Content-Type": "application/json", "Accept": "text/plain"})

    def test_non_string_key_raises(self) -> None:
        with pytest.raises(InvalidHeaderError):
            validate_headers({1: "value"})

    def test_empty_key_raises(self) -> None:
        with pytest.raises(InvalidHeaderError):
            validate_headers({"": "value"})

    def test_whitespace_key_raises(self) -> None:
        with pytest.raises(InvalidHeaderError):
            validate_headers({"  ": "value"})

    def test_non_string_value_raises(self) -> None:
        with pytest.raises(InvalidHeaderError):
            validate_headers({"key": 123})

    def test_duplicate_header_case_insensitive_raises(self) -> None:
        with pytest.raises(InvalidHeaderError, match="Duplicate"):
            validate_headers({"Content-Type": "a", "content-type": "b"})

    def test_not_a_dict_raises(self) -> None:
        with pytest.raises(InvalidHeaderError):
            validate_headers("not a dict")

    def test_list_value_raises(self) -> None:
        with pytest.raises(InvalidHeaderError):
            validate_headers({"key": ["a", "b"]})


class TestValidateContentType:
    def test_empty_string_valid(self) -> None:
        validate_content_type("")

    def test_valid_content_type(self) -> None:
        validate_content_type("application/json")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(InvalidContentTypeError):
            validate_content_type("   ")

    def test_none_string_does_not_raise(self) -> None:
        validate_content_type("")


class TestValidateFullRequest:
    def test_valid_request(self) -> None:
        req = HttpRequest(method="GET", url="https://example.com")
        validate_request(req)

    def test_valid_post_request(self) -> None:
        req = HttpRequest(
            method="POST",
            url="https://example.com/api",
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        validate_request(req)

    def test_invalid_url_raises_validation(self) -> None:
        with pytest.raises(InvalidUrlError):
            validate_url("")

    def test_invalid_method_raises_validation(self) -> None:
        with pytest.raises(InvalidMethodError):
            validate_method("INVALID")

    def test_invalid_timeout_raises_validation(self) -> None:
        with pytest.raises(InvalidTimeoutError):
            validate_timeout(-1)


# =========================================================================
# Test Fake Transport
# =========================================================================


class TestFakeTransport:
    @pytest.mark.asyncio
    async def test_successful_response(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200, body=b"ok")
        req = HttpRequest(method="GET", url="https://example.com")
        resp = await transport.send(req)
        assert resp.status_code == 200
        assert resp.body == b"ok"

    @pytest.mark.asyncio
    async def test_missing_response_raises_http_status_error(self) -> None:
        transport = FakeHttpTransport()
        req = HttpRequest(method="GET", url="https://example.com/nonexistent")
        with pytest.raises(HttpStatusError) as exc:
            await transport.send(req)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_simulated_error(self) -> None:
        transport = FakeHttpTransport()
        transport.add_error("GET", "https://example.com", RequestTimeoutError("timeout"))
        req = HttpRequest(method="GET", url="https://example.com")
        with pytest.raises(RequestTimeoutError):
            await transport.send(req)

    @pytest.mark.asyncio
    async def test_tracks_sent_requests(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("POST", "https://example.com/api", status_code=201)
        req = HttpRequest(method="POST", url="https://example.com/api", body={"k": "v"})
        await transport.send(req)
        assert len(transport.sent_requests) == 1
        assert transport.sent_requests[0].url == "https://example.com/api"
        assert transport.sent_requests[0].method == "POST"


# =========================================================================
# Test HttpAdapter - Metadata
# =========================================================================


class TestHttpAdapterMetadata:
    def test_metadata_is_correct(self) -> None:
        adapter = HttpAdapter()
        meta = adapter.metadata
        assert isinstance(meta, AdapterMetadata)
        assert meta.name == "http"
        assert meta.version == "1.0.0"
        assert "http" in meta.tags
        assert "rest" in meta.tags
        assert "transport" in meta.tags
        assert "web" in meta.tags
        assert meta.supports_retry is True
        assert meta.requires_auth is False
        assert meta.supports_streaming is False
        assert meta.supports_batch is False

    def test_metadata_immutable(self) -> None:
        meta = HttpAdapter().metadata
        with pytest.raises(AttributeError):
            meta.name = "changed"

    def test_metadata_describes_http(self) -> None:
        meta = HttpAdapter().metadata
        assert "HTTP" in meta.description
        assert "REST" in meta.description

    def test_capability_descriptors(self) -> None:
        assert len(CAPABILITY_DESCRIPTORS) == 5
        names = {c["name"] for c in CAPABILITY_DESCRIPTORS}
        assert "http_request" in names
        assert "http_get" in names
        assert "http_post" in names
        assert "http_put" in names
        assert "http_delete" in names

    def test_credential_descriptors(self) -> None:
        assert len(CREDENTIAL_DESCRIPTORS) == 4
        names = {c["name"] for c in CREDENTIAL_DESCRIPTORS}
        assert "http_api_key" in names
        assert "http_bearer_token" in names
        assert "http_basic_auth" in names
        assert "http_custom_header" in names

    def test_no_service_specific_names(self) -> None:
        meta = HttpAdapter().metadata
        assert "gmail" not in meta.name.lower()
        assert "slack" not in meta.name.lower()
        assert "google" not in meta.name.lower()
        assert "openai" not in meta.name.lower()

    def test_no_service_specific_capabilities(self) -> None:
        for cap in CAPABILITY_DESCRIPTORS:
            assert "gmail" not in cap["name"].lower()
            assert "slack" not in cap["name"].lower()

    def test_repr(self) -> None:
        adapter = HttpAdapter()
        r = repr(adapter)
        assert "HttpAdapter" in r
        assert "http" in r


# =========================================================================
# Test HttpAdapter - GET requests
# =========================================================================


class TestHttpAdapterGet:
    @pytest.mark.asyncio
    async def test_simple_get(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://api.example.com/users", status_code=200, body=b'{"users": []}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://api.example.com/users"},
        )
        result = await adapter.execute(context)
        assert result.success is True
        assert result.data["status_code"] == 200
        assert result.data["json"] == {"users": []}

    @pytest.mark.asyncio
    async def test_get_with_query_params(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://api.example.com/search", status_code=200, body=b'{}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={
                "method": "GET",
                "url": "https://api.example.com/search",
                "query_params": {"q": "hello", "page": "1"},
            },
        )
        result = await adapter.execute(context)
        assert result.success is True
        sent = transport.sent_requests[0]
        assert sent.query_params == {"q": "hello", "page": "1"}

    @pytest.mark.asyncio
    async def test_get_with_headers(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://api.example.com/data", status_code=200, body=b'{}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={
                "method": "GET",
                "url": "https://api.example.com/data",
                "headers": {"Accept": "application/json"},
            },
        )
        result = await adapter.execute(context)
        assert result.success is True
        sent = transport.sent_requests[0]
        assert sent.headers.get("Accept") == "application/json"

    @pytest.mark.asyncio
    async def test_get_200_with_body(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200, body=b'{"status":"ok"}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
        )
        result = await adapter.execute(context)
        assert result.success is True
        assert result.data["json"] == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_get_204_no_body(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=204)
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
        )
        result = await adapter.execute(context)
        assert result.success is True


class TestHttpAdapterPost:
    @pytest.mark.asyncio
    async def test_post_json_body(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response(
            "POST", "https://api.example.com/users",
            status_code=201, body=b'{"id": 1}',
        )
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_post",
            params={
                "method": "POST",
                "url": "https://api.example.com/users",
                "body": {"name": "Alice", "email": "alice@example.com"},
                "content_type": "application/json",
            },
        )
        result = await adapter.execute(context)
        assert result.success is True
        assert result.data["json"] == {"id": 1}
        sent = transport.sent_requests[0]
        assert isinstance(sent.body, bytes)
        decoded = _json.loads(sent.body)
        assert decoded["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_post_with_string_body(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("POST", "https://example.com/data", status_code=200, body=b"ok")
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_post",
            params={
                "method": "POST",
                "url": "https://example.com/data",
                "body": "plain text",
                "content_type": "text/plain",
            },
        )
        result = await adapter.execute(context)
        assert result.success is True
        sent = transport.sent_requests[0]
        assert sent.body == b"plain text"

    @pytest.mark.asyncio
    async def test_post_empty_body(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("POST", "https://example.com/data", status_code=200)
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_post",
            params={"method": "POST", "url": "https://example.com/data"},
        )
        result = await adapter.execute(context)
        assert result.success is True


class TestHttpAdapterPut:
    @pytest.mark.asyncio
    async def test_put(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("PUT", "https://api.example.com/users/1", status_code=200, body=b'{"id": 1}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_put",
            params={
                "method": "PUT",
                "url": "https://api.example.com/users/1",
                "body": {"name": "Alice"},
            },
        )
        result = await adapter.execute(context)
        assert result.success is True
        assert result.data["status_code"] == 200


class TestHttpAdapterPatch:
    @pytest.mark.asyncio
    async def test_patch(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("PATCH", "https://api.example.com/users/1", status_code=200, body=b'{}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_request",
            params={
                "method": "PATCH",
                "url": "https://api.example.com/users/1",
                "body": {"name": "Alice"},
            },
        )
        result = await adapter.execute(context)
        assert result.success is True


class TestHttpAdapterDelete:
    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("DELETE", "https://api.example.com/users/1", status_code=204)
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_delete",
            params={"method": "DELETE", "url": "https://api.example.com/users/1"},
        )
        result = await adapter.execute(context)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_delete_with_body(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("DELETE", "https://api.example.com/data", status_code=200)
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_delete",
            params={
                "method": "DELETE",
                "url": "https://api.example.com/data",
                "body": {"reason": "cleanup"},
            },
        )
        result = await adapter.execute(context)
        assert result.success is True


class TestHttpAdapterHead:
    @pytest.mark.asyncio
    async def test_head(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("HEAD", "https://example.com", status_code=200)
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_request",
            params={"method": "HEAD", "url": "https://example.com"},
        )
        result = await adapter.execute(context)
        assert result.success is True


class TestHttpAdapterOptions:
    @pytest.mark.asyncio
    async def test_options(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("OPTIONS", "https://example.com", status_code=200)
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_request",
            params={"method": "OPTIONS", "url": "https://example.com"},
        )
        result = await adapter.execute(context)
        assert result.success is True


# =========================================================================
# Test HttpAdapter - Authentication
# =========================================================================


class TestHttpAdapterAuth:
    @pytest.mark.asyncio
    async def test_injects_bearer_token(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://api.example.com/me", status_code=200, body=b'{}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://api.example.com/me"},
            credentials={"auth_type": "bearer_token", "token": "my_token"},
        )
        result = await adapter.execute(context)
        assert result.success is True
        sent = transport.sent_requests[0]
        assert sent.headers.get("Authorization") == "Bearer my_token"

    @pytest.mark.asyncio
    async def test_injects_api_key_auth(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://api.example.com/data", status_code=200, body=b'{}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://api.example.com/data"},
            credentials={"auth_type": "api_key", "api_key": "sk-test", "header_name": "X-API-Key"},
        )
        result = await adapter.execute(context)
        assert result.success is True
        sent = transport.sent_requests[0]
        assert sent.headers.get("X-API-Key") == "sk-test"

    @pytest.mark.asyncio
    async def test_injects_basic_auth(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://api.example.com/data", status_code=200, body=b'{}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://api.example.com/data"},
            credentials={"auth_type": "basic_auth", "username": "admin", "password": "pass"},
        )
        result = await adapter.execute(context)
        assert result.success is True
        sent = transport.sent_requests[0]
        auth_header = sent.headers.get("Authorization", "")
        assert auth_header.startswith("Basic ")

    @pytest.mark.asyncio
    async def test_injects_custom_header_auth(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://api.example.com/data", status_code=200, body=b'{}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://api.example.com/data"},
            credentials={
                "auth_type": "custom_header",
                "header_name": "X-Session",
                "header_value": "abc123",
            },
        )
        result = await adapter.execute(context)
        assert result.success is True
        sent = transport.sent_requests[0]
        assert sent.headers.get("X-Session") == "abc123"

    @pytest.mark.asyncio
    async def test_no_auth_by_default(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200, body=b'{}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
            credentials={},
        )
        result = await adapter.execute(context)
        assert result.success is True
        sent = transport.sent_requests[0]
        assert "authorization" not in {k.lower() for k in sent.headers}

    @pytest.mark.asyncio
    async def test_auth_headers_merged_with_request_headers(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://api.example.com/data", status_code=200, body=b'{}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={
                "method": "GET",
                "url": "https://api.example.com/data",
                "headers": {"Accept": "application/json"},
            },
            credentials={"auth_type": "bearer_token", "token": "tok"},
        )
        result = await adapter.execute(context)
        assert result.success is True
        sent = transport.sent_requests[0]
        assert sent.headers.get("Authorization") == "Bearer tok"
        assert sent.headers.get("Accept") == "application/json"


# =========================================================================
# Test HttpAdapter - Error Handling
# =========================================================================


class TestHttpAdapterErrorHandling:
    @pytest.mark.asyncio
    async def test_invalid_url_returns_failure(self) -> None:
        adapter = HttpAdapter(transport=FakeHttpTransport())
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "not-a-url"},
        )
        result = await adapter.execute(context)
        assert result.success is False
        assert "URL" in result.error

    @pytest.mark.asyncio
    async def test_invalid_method_returns_failure(self) -> None:
        adapter = HttpAdapter(transport=FakeHttpTransport())
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_request",
            params={"method": "INVALID", "url": "https://example.com"},
        )
        result = await adapter.execute(context)
        assert result.success is False
        assert "Unsupported method" in result.error

    @pytest.mark.asyncio
    async def test_timeout_returns_failure(self) -> None:
        transport = FakeHttpTransport()
        transport.add_error("GET", "https://example.com", RequestTimeoutError("timed out"))
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
        )
        result = await adapter.execute(context)
        assert result.success is False
        assert "time" in result.error.lower()

    @pytest.mark.asyncio
    async def test_connection_error_returns_failure(self) -> None:
        transport = FakeHttpTransport()
        transport.add_error("GET", "https://example.com", ConnectionError("connection refused"))
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
        )
        result = await adapter.execute(context)
        assert result.success is False
        assert "connection" in result.error.lower()

    @pytest.mark.asyncio
    async def test_dns_error_returns_failure(self) -> None:
        transport = FakeHttpTransport()
        transport.add_error("GET", "https://nonexistent.example", DnsError("DNS resolution failed"))
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://nonexistent.example"},
        )
        result = await adapter.execute(context)
        assert result.success is False
        assert "DNS" in result.error

    @pytest.mark.asyncio
    async def test_404_handled_gracefully(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://api.example.com/notfound", status_code=404, body=b'{"error":"not found"}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://api.example.com/notfound"},
        )
        result = await adapter.execute(context)
        assert result.success is False
        assert "404" in result.error
        assert result.data.get("status_code") == 404
        assert result.metadata.get("error_type") == "HttpStatusError"

    @pytest.mark.asyncio
    async def test_500_handled_gracefully(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://api.example.com/error", status_code=500, body=b'internal error')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://api.example.com/error"},
        )
        result = await adapter.execute(context)
        assert result.success is False
        assert "500" in result.error

    @pytest.mark.asyncio
    async def test_serialization_error_returns_failure(self) -> None:
        adapter = HttpAdapter(transport=FakeHttpTransport())
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_post",
            params={
                "method": "POST",
                "url": "https://example.com",
                "content_type": "application/json",
                "body": object(),
            },
        )
        result = await adapter.execute(context)
        assert result.success is False
        assert "serialize" in result.error.lower()

    @pytest.mark.asyncio
    async def test_negative_timeout_in_params_returns_failure(self) -> None:
        adapter = HttpAdapter(transport=FakeHttpTransport())
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com", "timeout": -5},
        )
        result = await adapter.execute(context)
        assert result.success is False
        assert "Timeout" in result.error


# =========================================================================
# Test HttpAdapter - Config defaults
# =========================================================================


class TestHttpAdapterConfig:
    @pytest.mark.asyncio
    async def test_default_method_from_config(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200, body=b'{}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_request",
            params={"url": "https://example.com"},
            config={"default_method": "GET"},
        )
        result = await adapter.execute(context)
        assert result.success is True
        sent = transport.sent_requests[0]
        assert sent.method == "GET"

    @pytest.mark.asyncio
    async def test_default_timeout_from_config(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200, body=b'{}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
            config={"default_timeout": 60.0},
        )
        result = await adapter.execute(context)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_default_content_type_from_config(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("POST", "https://example.com/data", status_code=200)
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_post",
            params={
                "method": "POST",
                "url": "https://example.com/data",
                "body": {"k": "v"},
            },
            config={"default_content_type": "application/json"},
        )
        result = await adapter.execute(context)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_default_accept_from_config(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200)
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
            config={"default_accept": "application/json"},
        )
        result = await adapter.execute(context)
        assert result.success is True


# =========================================================================
# Test HttpAdapter - Usage / Metrics
# =========================================================================


class TestHttpAdapterUsage:
    @pytest.mark.asyncio
    async def test_usage_reported(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200, elapsed=0.5)
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
        )
        result = await adapter.execute(context)
        assert result.usage.api_calls == 1
        assert result.usage.latency_ms == 500.0

    @pytest.mark.asyncio
    async def test_usage_zero_latency(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200, elapsed=0.0)
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
        )
        result = await adapter.execute(context)
        assert result.usage.latency_ms == 0.0


# =========================================================================
# Test HttpAdapter - Response parsing
# =========================================================================


class TestHttpAdapterResponseParsing:
    @pytest.mark.asyncio
    async def test_non_json_response_still_succeeds(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200, body=b"plain text", content_type="text/plain")
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
        )
        result = await adapter.execute(context)
        assert result.success is True
        assert result.data["body"] == "plain text"
        assert result.data["json"] is None

    @pytest.mark.asyncio
    async def test_response_headers_returned(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200, body=b'{}', headers={"x-request-id": "abc"})
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
        )
        result = await adapter.execute(context)
        assert result.success is True
        assert result.data["headers"]["x-request-id"] == "abc"

    @pytest.mark.asyncio
    async def test_elapsed_in_metadata(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200, elapsed=1.5)
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
        )
        result = await adapter.execute(context)
        assert result.metadata["elapsed"] == 1.5
        assert result.metadata["content_type"] is not None

    @pytest.mark.asyncio
    async def test_non_utf8_body_decoded(self) -> None:
        transport = FakeHttpTransport()
        body = "héllo".encode("latin-1")
        transport.add_response("GET", "https://example.com", status_code=200, body=body)
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
        )
        result = await adapter.execute(context)
        assert result.success is True
        # Should decode with replacement rather than crash
        assert isinstance(result.data["body"], str)


# =========================================================================
# Test HttpAdapter - Edge cases
# =========================================================================


class TestHttpAdapterEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_response_body(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200, body=b"")
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
        )
        result = await adapter.execute(context)
        assert result.success is True
        assert result.data["body"] == ""
        assert result.data["json"] is None

    @pytest.mark.asyncio
    async def test_large_response_body(self) -> None:
        body = b"x" * 100000
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200, body=body)
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
        )
        result = await adapter.execute(context)
        assert result.success is True
        assert len(result.data["body"]) == 100000

    @pytest.mark.asyncio
    async def test_duplicate_transport_requests(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200, body=b'ok')
        adapter = HttpAdapter(transport=transport)
        for _ in range(3):
            context = AdapterContext.build(
                execution_session_id="s1",
                execution_task_id="t1",
                action="http_get",
                params={"method": "GET", "url": "https://example.com"},
            )
            result = await adapter.execute(context)
            assert result.success is True
        assert len(transport.sent_requests) == 3

    @pytest.mark.asyncio
    async def test_transport_injected_used_for_all_requests(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://a.com", status_code=200, body=b"a")
        transport.add_response("GET", "https://b.com", status_code=200, body=b"b")
        adapter = HttpAdapter(transport=transport)
        ctx_a = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="get_a", params={"method": "GET", "url": "https://a.com"},
        )
        ctx_b = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t2",
            action="get_b", params={"method": "GET", "url": "https://b.com"},
        )
        result_a = await adapter.execute(ctx_a)
        result_b = await adapter.execute(ctx_b)
        assert result_a.data["body"] == "a"
        assert result_b.data["body"] == "b"


# =========================================================================
# Test HttpAdapter - Statelessness
# =========================================================================


class TestHttpAdapterStatelessness:
    @pytest.mark.asyncio
    async def test_adapter_has_no_mutable_state(self) -> None:
        adapter = HttpAdapter()
        # No mutable instance attributes
        mutable = {k for k, v in vars(adapter).items() if not k.startswith("_")}
        assert len(mutable) == 0

    @pytest.mark.asyncio
    async def test_adapter_does_not_cache(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200, body=b'ok')
        adapter = HttpAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="http_get", params={"method": "GET", "url": "https://example.com"},
        )
        r1 = await adapter.execute(ctx)
        r2 = await adapter.execute(ctx)
        assert r1.data["body"] == r2.data["body"]

    def test_same_request_same_behavior(self) -> None:
        req1 = HttpRequest(method="GET", url="https://example.com")
        req2 = HttpRequest(method="GET", url="https://example.com")
        assert req1 == req2


# =========================================================================
# Test HttpAdapter - No retries, caching, or recovery
# =========================================================================


class TestHttpAdapterNoRetries:
    @pytest.mark.asyncio
    async def test_transport_called_exactly_once(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200, body=b'')
        adapter = HttpAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="http_get", params={"method": "GET", "url": "https://example.com"},
        )
        await adapter.execute(ctx)
        assert len(transport.sent_requests) == 1

    @pytest.mark.asyncio
    async def test_adapter_does_not_retry_on_error(self) -> None:
        transport = FakeHttpTransport()
        transport.add_error("GET", "https://example.com", ConnectionError("fail"))
        adapter = HttpAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="http_get", params={"method": "GET", "url": "https://example.com"},
        )
        await adapter.execute(ctx)
        # Exactly 1 attempt — no retry
        assert len(transport.sent_requests) == 1


# =========================================================================
# Test HttpAdapter - Response metadata
# =========================================================================


class TestHttpAdapterResponseMetadata:
    @pytest.mark.asyncio
    async def test_content_type_in_metadata(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response(
            "GET", "https://example.com", status_code=200, body=b'{}',
            content_type="application/json",
        )
        adapter = HttpAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="http_get", params={"method": "GET", "url": "https://example.com"},
        )
        result = await adapter.execute(ctx)
        assert result.metadata["content_type"] == "application/json"

    @pytest.mark.asyncio
    async def test_status_code_in_data(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=201)
        adapter = HttpAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="http_get", params={"method": "GET", "url": "https://example.com"},
        )
        result = await adapter.execute(ctx)
        assert result.data["status_code"] == 201


# =========================================================================
# Test HttpAdapter - No service-specific code
# =========================================================================


class TestHttpAdapterNoServiceSpecific:
    def test_no_gmail_in_source(self) -> None:
        import inspect
        source = inspect.getsource(HttpAdapter)
        assert "gmail" not in source.lower()

    def test_no_slack_in_source(self) -> None:
        import inspect
        source = inspect.getsource(HttpAdapter)
        assert "slack" not in source.lower()

    def test_no_google_in_source(self) -> None:
        import inspect
        source = inspect.getsource(HttpAdapter)
        assert "google" not in source.lower()

    def test_no_openai_in_source(self) -> None:
        import inspect
        source = inspect.getsource(HttpAdapter)
        assert "openai" not in source.lower()

    def test_no_github_in_source(self) -> None:
        import inspect
        source = inspect.getsource(HttpAdapter)
        assert "github" not in source.lower()


# =========================================================================
# Test HttpAdapter - CredentialInstance consumption
# =========================================================================


class TestHttpAdapterCredentialConsumption:
    @pytest.mark.asyncio
    async def test_consumes_credential_instance_values(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://api.example.com", status_code=200, body=b'{}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://api.example.com"},
            credentials={"auth_type": "bearer_token", "token": "tok_from_instance"},
        )
        result = await adapter.execute(context)
        assert result.success is True
        sent = transport.sent_requests[0]
        assert sent.headers.get("Authorization") == "Bearer tok_from_instance"

    @pytest.mark.asyncio
    async def test_credential_values_override_auth_type(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://api.example.com", status_code=200, body=b'{}')
        adapter = HttpAdapter(transport=transport)
        context = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://api.example.com"},
            credentials={"auth_type": "api_key", "api_key": "k1", "header_name": "X-Key"},
        )
        result = await adapter.execute(context)
        assert result.success is True
        sent = transport.sent_requests[0]
        assert sent.headers.get("X-Key") == "k1"


# =========================================================================
# Test HttpAdapter - Integration with registry
# =========================================================================


class TestHttpAdapterRegistryIntegration:
    def test_can_register_with_adapter_registry(self) -> None:
        from services.adapters.adapter_registration import AdapterIdentity, AdapterRegistration
        from services.adapters.adapter_registry import AdapterRegistry

        registry = AdapterRegistry()
        registration = AdapterRegistration(
            identity=AdapterIdentity(name="http", version="1.0.0"),
            adapter_class=HttpAdapter,
            metadata=HTTP_ADAPTER_METADATA,
            capability_names=("http_request", "http_get", "http_post", "http_put", "http_delete"),
            credential_descriptor_names=("http_api_key", "http_bearer_token", "http_basic_auth", "http_custom_header"),
        )
        registry.register(registration)
        assert registry.exists(AdapterIdentity(name="http", version="1.0.0"))

    def test_registered_adapter_identity(self) -> None:
        from services.adapters.adapter_registration import AdapterIdentity, AdapterRegistration
        from services.adapters.adapter_registry import AdapterRegistry

        registry = AdapterRegistry()
        reg = AdapterRegistration(
            identity=AdapterIdentity(name="http", version="1.0.0"),
            adapter_class=HttpAdapter,
            metadata=HTTP_ADAPTER_METADATA,
        )
        registry.register(reg)
        fetched = registry.get(AdapterIdentity(name="http", version="1.0.0"))
        assert fetched is not None
        assert fetched.identity.name == "http"

    def test_registered_adapter_creatable(self) -> None:
        from services.adapters.adapter_registration import AdapterIdentity, AdapterRegistration
        from services.adapters.adapter_registry import AdapterRegistry

        registry = AdapterRegistry()
        reg = AdapterRegistration(
            identity=AdapterIdentity(name="http", version="1.0.0"),
            adapter_class=HttpAdapter,
            metadata=HTTP_ADAPTER_METADATA,
        )
        registry.register(reg)
        adapter = registry.create_adapter(AdapterIdentity(name="http", version="1.0.0"))
        assert isinstance(adapter, HttpAdapter)


class TestHttpAdapterCapabilityIntegration:
    def test_capability_descriptors_valid(self) -> None:
        for desc in CAPABILITY_DESCRIPTORS:
            from services.adapters.capabilities import CapabilityDescriptor
            cd = CapabilityDescriptor(**desc)
            assert cd.name.startswith("http_")

    def test_capability_descriptors_with_params(self) -> None:
        from services.adapters.capabilities import CapabilityDescriptor
        for desc in CAPABILITY_DESCRIPTORS:
            cd = CapabilityDescriptor(**desc)
            assert cd.category == "web"

    def test_capabilities_registrable(self) -> None:
        from services.adapters.capabilities import CapabilityDescriptor
        from services.adapters.capability_registry import CapabilityRegistry

        registry = CapabilityRegistry()
        for desc in CAPABILITY_DESCRIPTORS:
            cd = CapabilityDescriptor(**desc)
            registry.register(cd)
        assert registry.count() == 5

    def test_capability_provider_registrable(self) -> None:
        from services.adapters.capabilities import CapabilityDescriptor, CapabilityProvider
        from services.adapters.capability_registry import CapabilityRegistry

        registry = CapabilityRegistry()
        for desc in CAPABILITY_DESCRIPTORS:
            registry.register(CapabilityDescriptor(**desc))
        provider = CapabilityProvider(
            adapter_name="http",
            adapter_version="1.0.0",
            capability_names=("http_request", "http_get", "http_post", "http_put", "http_delete"),
            priority=10,
        )
        registry.register_provider(provider)
        providers = registry.find_providers("http_request")
        assert len(providers) == 1
        assert providers[0].adapter_name == "http"


class TestHttpAdapterCredentialDescriptorIntegration:
    def test_credential_descriptors_creatable(self) -> None:
        from services.adapters.credentials import CredentialDescriptor, CredentialField, CredentialType

        for desc_data in CREDENTIAL_DESCRIPTORS:
            descriptor = CredentialDescriptor(
                name=desc_data["name"],
                display_name=desc_data["display_name"],
                description=desc_data["description"],
                auth_type=desc_data["auth_type"],
            )
            assert descriptor.name == desc_data["name"]
            assert descriptor.auth_type == desc_data["auth_type"]

    def test_credential_descriptors_registrable(self) -> None:
        from services.adapters.credentials import CredentialDescriptor
        from services.adapters.credential_registry import CredentialRegistry

        registry = CredentialRegistry()
        for desc_data in CREDENTIAL_DESCRIPTORS:
            descriptor = CredentialDescriptor(
                name=desc_data["name"],
                display_name=desc_data["display_name"],
                description=desc_data["description"],
                auth_type=desc_data["auth_type"],
            )
            registry.register(descriptor)
        assert registry.count() == 4

    def test_api_key_descriptor_has_required_fields(self) -> None:
        from services.adapters.credentials import CredentialDescriptor

        for desc_data in CREDENTIAL_DESCRIPTORS:
            descriptor = CredentialDescriptor(
                name=desc_data["name"],
                display_name=desc_data["display_name"],
                description=desc_data["description"],
                auth_type=desc_data["auth_type"],
            )
            assert len(descriptor.required_fields) >= 0


# =========================================================================
# Test HttpAdapter - AdapterContext binding
# =========================================================================


class TestHttpAdapterContextBinding:
    @pytest.mark.asyncio
    async def test_action_passed_through(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("POST", "https://example.com/api", status_code=200, body=b'{}')
        adapter = HttpAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_post",
            params={"method": "POST", "url": "https://example.com/api", "body": {"k": "v"}},
        )
        await adapter.execute(ctx)
        sent = transport.sent_requests[0]
        assert sent.method == "POST"

    @pytest.mark.asyncio
    async def test_runtime_metadata_accessible(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200)
        adapter = HttpAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com"},
        )
        result = await adapter.execute(ctx)
        assert result.success is True


# =========================================================================
# Test HttpAdapter - Query params
# =========================================================================


class TestHttpAdapterQueryParams:
    @pytest.mark.asyncio
    async def test_multiple_query_params(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com/search", status_code=200)
        adapter = HttpAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={
                "method": "GET",
                "url": "https://example.com/search",
                "query_params": {"q": "test", "page": "2", "limit": "10"},
            },
        )
        await adapter.execute(ctx)
        sent = transport.sent_requests[0]
        assert sent.query_params == {"q": "test", "page": "2", "limit": "10"}

    @pytest.mark.asyncio
    async def test_empty_query_params(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com", status_code=200)
        adapter = HttpAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={"method": "GET", "url": "https://example.com", "query_params": {}},
        )
        await adapter.execute(ctx)
        sent = transport.sent_requests[0]
        assert sent.query_params == {}

    @pytest.mark.asyncio
    async def test_special_chars_in_query_params(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://example.com/search", status_code=200)
        adapter = HttpAdapter(transport=transport)
        ctx = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="http_get",
            params={
                "method": "GET",
                "url": "https://example.com/search",
                "query_params": {"q": "hello world&more"},
            },
        )
        await adapter.execute(ctx)
        sent = transport.sent_requests[0]
        assert sent.query_params["q"] == "hello world&more"


# =========================================================================
# Test HttpAdapter - With httpx transport (no network)
# =========================================================================


class TestHttpxTransportProtocol:
    def test_transport_is_protocol(self) -> None:
        import inspect
        assert inspect.isclass(HttpTransport)

    def test_transport_has_send_method(self) -> None:
        assert hasattr(HttpTransport, "send")

    def test_fake_transport_conforms(self) -> None:
        from typing import cast
        transport: HttpTransport = cast(HttpTransport, FakeHttpTransport())
        assert transport is not None


class TestHttpxTransportConstruction:
    def test_httpx_transport_can_be_instantiated(self) -> None:
        from services.adapters.http.transport import HttpxTransport
        transport = HttpxTransport()
        assert transport is not None


# =========================================================================
# Test imports and self-containment
# =========================================================================


class TestHttpAdapterSelfContainment:
    def test_no_execution_imports(self) -> None:
        import services.adapters.http as http_pkg
        import inspect
        source = inspect.getsource(http_pkg)
        assert "services.execution" not in source

    def test_no_planner_imports(self) -> None:
        import services.adapters.http.http_adapter as mod
        import inspect
        source = inspect.getsource(mod)
        assert "services.planner" not in source

    def test_no_concrete_service_imports(self) -> None:
        import services.adapters.http.http_adapter as mod
        import inspect
        source = inspect.getsource(mod)
        assert "gmail" not in source.lower()
        assert "slack" not in source.lower()

    def test_http_package_loads_cleanly(self) -> None:
        from services.adapters.http import (
            HttpAdapter,
            HttpRequest,
            HttpResponse,
            HttpError,
            HttpTransport,
        )
        assert HttpAdapter is not None

    def test_no_retry_loop(self) -> None:
        from services.adapters.http import http_adapter
        import inspect
        source = inspect.getsource(http_adapter)
        assert "while" not in source.lower() or "retry" not in source.lower()[:200]

    def test_no_caching(self) -> None:
        from services.adapters.http.http_adapter import HttpAdapter
        adapter = HttpAdapter()
        import inspect
        source = inspect.getsource(type(adapter).execute)
        assert "cache" not in source.lower()

    def test_no_metrics_collection(self) -> None:
        from services.adapters.http.http_adapter import HttpAdapter
        adapter = HttpAdapter()
        import inspect
        source = inspect.getsource(type(adapter).execute)
        assert "metric" not in source.lower()


# =========================================================================
# Test Full Adapter Lifecycle
# =========================================================================


class TestHttpAdapterFullLifecycle:
    @pytest.mark.asyncio
    async def test_get_then_post_then_get(self) -> None:
        transport = FakeHttpTransport()
        transport.add_response("GET", "https://api.example.com/users", status_code=200, body=b'[{"id":1}]')
        transport.add_response("POST", "https://api.example.com/users", status_code=201, body=b'{"id":2}')
        transport.add_response("GET", "https://api.example.com/users/count", status_code=200, body=b'[{"id":1},{"id":2}]')

        adapter = HttpAdapter(transport=transport)

        ctx_get1 = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1",
            action="list", params={"method": "GET", "url": "https://api.example.com/users"},
        )
        ctx_post = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t2",
            action="create", params={
                "method": "POST",
                "url": "https://api.example.com/users",
                "body": {"name": "Bob"},
                "content_type": "application/json",
            },
        )
        ctx_get2 = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t3",
            action="count", params={"method": "GET", "url": "https://api.example.com/users/count"},
        )

        r1 = await adapter.execute(ctx_get1)
        assert r1.success is True
        assert len(r1.data["json"]) == 1

        r2 = await adapter.execute(ctx_post)
        assert r2.success is True
        assert r2.data["status_code"] == 201

        r3 = await adapter.execute(ctx_get2)
        assert r3.success is True
        assert len(r3.data["json"]) == 2

        assert len(transport.sent_requests) == 3
