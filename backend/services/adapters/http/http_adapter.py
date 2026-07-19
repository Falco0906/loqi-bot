from __future__ import annotations

from typing import Any

from services.adapters.base_adapter import ExecutionAdapter
from services.adapters.http.auth import resolve_auth
from services.adapters.http.exceptions import (
    ConnectionError as HttpConnectionError,
    DeserializationError,
    DnsError,
    HttpError,
    HttpStatusError,
    RequestTimeoutError,
    SerializationError,
)
from services.adapters.http.models import HttpRequest, SUPPORTED_METHODS
from services.adapters.http.serializers import detect_serializer
from services.adapters.http.transport import HttpTransport

from services.adapters.models import AdapterMetadata, AdapterResult, UsageInfo
from services.adapters.adapter_context import AdapterContext

CAPABILITY_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": "http_request",
        "display_name": "HTTP Request",
        "description": "Execute a generic HTTP request",
        "category": "web",
        "version": "1.0.0",
        "requires_auth": True,
    },
    {
        "name": "http_get",
        "display_name": "HTTP GET",
        "description": "Execute an HTTP GET request",
        "category": "web",
        "version": "1.0.0",
        "requires_auth": False,
    },
    {
        "name": "http_post",
        "display_name": "HTTP POST",
        "description": "Execute an HTTP POST request",
        "category": "web",
        "version": "1.0.0",
        "requires_auth": True,
    },
    {
        "name": "http_put",
        "display_name": "HTTP PUT",
        "description": "Execute an HTTP PUT request",
        "category": "web",
        "version": "1.0.0",
        "requires_auth": True,
    },
    {
        "name": "http_delete",
        "display_name": "HTTP DELETE",
        "description": "Execute an HTTP DELETE request",
        "category": "web",
        "version": "1.0.0",
        "requires_auth": True,
    },
]

CREDENTIAL_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": "http_api_key",
        "display_name": "HTTP API Key",
        "description": "API key authentication for HTTP requests",
        "auth_type": "api_key",
    },
    {
        "name": "http_bearer_token",
        "display_name": "HTTP Bearer Token",
        "description": "Bearer token authentication for HTTP requests",
        "auth_type": "bearer_token",
    },
    {
        "name": "http_basic_auth",
        "display_name": "HTTP Basic Auth",
        "description": "Basic username/password authentication for HTTP requests",
        "auth_type": "basic_auth",
    },
    {
        "name": "http_custom_header",
        "display_name": "HTTP Custom Header",
        "description": "Custom header authentication for HTTP requests",
        "auth_type": "custom_header",
    },
]

HTTP_ADAPTER_METADATA = AdapterMetadata(
    name="http",
    display_name="HTTP Adapter",
    version="1.0.0",
    description="Generic HTTP transport adapter — executes REST requests "
    "with authentication, serialization, and error mapping. "
    "No service-specific logic.",
    author="Loqi",
    supported_operations=tuple(sorted(SUPPORTED_METHODS)),
    requires_auth=False,
    supports_streaming=False,
    supports_batch=False,
    supports_retry=True,
    tags=("http", "rest", "transport", "web"),
)


class HttpAdapter(ExecutionAdapter):
    """Generic HTTP transport adapter.

    Executes HTTP requests with authentication injection, body
    serialization, response parsing, and structured error mapping.
    Contains zero service-specific logic.
    """

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self._transport = transport

    @property
    def metadata(self) -> AdapterMetadata:
        return HTTP_ADAPTER_METADATA

    async def execute(self, context: AdapterContext) -> AdapterResult:
        transport = self._get_transport(context)

        try:
            req = self._build_request(context)
        except HttpError as exc:
            return AdapterResult.failure_result(
                error=str(exc),
                metadata={"error_type": type(exc).__name__},
            )

        try:
            resp = await transport.send(req)
        except HttpStatusError as exc:
            return AdapterResult(
                success=False,
                error=str(exc),
                data={
                    "status_code": exc.status_code,
                    "body": exc.body,
                    "headers": exc.headers,
                },
                metadata={"error_type": "HttpStatusError"},
            )
        except RequestTimeoutError as exc:
            return AdapterResult.failure_result(
                error=str(exc),
                metadata={"error_type": "RequestTimeoutError"},
            )
        except (HttpConnectionError, DnsError) as exc:
            return AdapterResult.failure_result(
                error=str(exc),
                metadata={"error_type": type(exc).__name__},
            )
        except SerializationError as exc:
            return AdapterResult.failure_result(
                error=str(exc),
                metadata={"error_type": "SerializationError"},
            )
        except HttpError as exc:
            return AdapterResult.failure_result(
                error=str(exc),
                metadata={"error_type": type(exc).__name__},
            )

        try:
            json_data = resp.json
        except DeserializationError:
            json_data = None

        return AdapterResult.success_result(
            data={
                "status_code": resp.status_code,
                "body": resp.body.decode("utf-8", errors="replace"),
                "headers": dict(resp.headers),
                "json": json_data,
            },
            metadata={
                "elapsed": resp.elapsed,
                "content_type": resp.content_type,
            },
            usage=UsageInfo(api_calls=1, latency_ms=resp.elapsed * 1000),
        )

    def _build_request(self, context: AdapterContext) -> HttpRequest:
        params = context.params
        config = context.config
        credentials = context.credentials

        method = params.get("method", config.get("default_method", "GET")).upper()
        url = params.get("url", config.get("default_url", ""))
        headers = dict(params.get("headers", {}))
        query_params = dict(params.get("query_params", {}))
        body = params.get("body")
        timeout = params.get("timeout", config.get("default_timeout", 30.0))
        content_type = params.get(
            "content_type", config.get("default_content_type", "")
        )
        accept = params.get("accept", config.get("default_accept", ""))

        auth_strategy, auth_creds = resolve_auth(credentials)
        auth_headers = auth_strategy.apply(auth_creds)

        merged_headers = {**auth_headers, **headers}

        serializer = detect_serializer(body, content_type)
        if serializer and not content_type:
            content_type = serializer.content_type
        serialized_body = body
        if body is not None and serializer and not isinstance(body, bytes):
            serialized_body = serializer.serialize(body)

        return HttpRequest(
            method=method,
            url=url,
            headers=merged_headers,
            query_params=query_params,
            body=serialized_body,
            timeout=float(timeout),
            content_type=content_type,
            accept=accept,
        )

    def _get_transport(self, context: AdapterContext) -> HttpTransport:
        if self._transport is not None:
            return self._transport
        from services.adapters.http.transport import HttpxTransport

        return HttpxTransport()
