from __future__ import annotations

from typing import Any

from services.adapters.base_adapter import ExecutionAdapter
from services.adapters.google.errors import (
    GoogleApiErrorInfo,
    classify_google_status_code,
    parse_google_error_body,
)
from services.adapters.google.models import GoogleApiRequest
from services.adapters.google.pagination import next_page_token
from services.adapters.google.services import GoogleServiceDescriptor, GoogleServiceRegistry
from services.adapters.http.http_adapter import HttpAdapter
from services.adapters.http.transport import HttpTransport
from services.adapters.models import AdapterMetadata, AdapterResult
from services.adapters.adapter_context import AdapterContext

GOOGLE_API_METADATA = AdapterMetadata(
    name="google_api",
    display_name="Google API Adapter",
    version="1.0.0",
    description="Shared Google REST API adapter — builds Google API URLs, "
    "injects OAuth2 credentials, maps Google error payloads, "
    "and provides pagination helpers. "
    "No service-specific logic.",
    author="Loqi",
    supported_operations=("google_request", "google_paginated_request"),
    requires_auth=True,
    supports_streaming=False,
    supports_batch=False,
    supports_retry=True,
    tags=("google", "workspace", "oauth2"),
)

CAPABILITY_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": "google_request",
        "display_name": "Google API Request",
        "description": "Execute a generic Google REST API request",
        "category": "web",
        "version": "1.0.0",
        "requires_auth": True,
    },
    {
        "name": "google_paginated_request",
        "display_name": "Google API Paginated Request",
        "description": "Execute a Google REST API request with pagination support",
        "category": "web",
        "version": "1.0.0",
        "requires_auth": True,
    },
]

CREDENTIAL_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": "google_oauth2",
        "display_name": "Google OAuth2",
        "description": "OAuth2 access token for Google API authentication",
        "auth_type": "oauth2",
    },
]


class GoogleApiAdapter(ExecutionAdapter):
    """Shared Google REST API adapter.

    Builds Google API URLs from service descriptors, injects OAuth2
    bearer tokens, delegates HTTP execution to ``HttpAdapter``,
    maps Google error payloads to structured exceptions, and
    provides pagination helpers on responses.

    Contains zero Gmail-, Calendar-, Drive-, Docs-, or Sheets-
    specific logic.
    """

    def __init__(
        self,
        http_adapter: HttpAdapter | None = None,
        transport: HttpTransport | None = None,
        service_registry: GoogleServiceRegistry | None = None,
    ) -> None:
        self._http = http_adapter or HttpAdapter(transport=transport)
        self._registry = service_registry or GoogleServiceRegistry.with_defaults()

    @property
    def metadata(self) -> AdapterMetadata:
        return GOOGLE_API_METADATA

    async def execute(self, context: AdapterContext) -> AdapterResult:
        params = context.params

        service = params.get("service", "")
        resource = params.get("resource", "")
        version = params.get("version", "")
        method = params.get("method", "GET")
        query = dict(params.get("query", params.get("query_params", {})))
        body = params.get("body")
        timeout = params.get("timeout", 30.0)
        extra_headers = dict(params.get("headers", {}))

        if not service:
            return AdapterResult.failure_result(
                error="Missing required param 'service'",
                metadata={"error_type": "GoogleApiError"},
            )
        if not resource:
            return AdapterResult.failure_result(
                error="Missing required param 'resource'",
                metadata={"error_type": "GoogleApiError"},
            )

        descriptor = self._registry.get(service)
        if descriptor is None:
            return AdapterResult.failure_result(
                error=f"Unknown Google service {service!r}",
                metadata={"error_type": "GoogleApiError"},
            )

        credentials = context.credentials
        access_token = credentials.get("access_token", "")
        token_type = credentials.get("token_type", "Bearer")

        if not access_token:
            return AdapterResult.failure_result(
                error="Missing OAuth2 access_token in credentials",
                metadata={"error_type": "GoogleAuthenticationError"},
            )

        google_req = GoogleApiRequest(
            service=service,
            resource=resource,
            version=version,
            method=method,
            query=query,
            body=body,
            headers=extra_headers,
            timeout=float(timeout),
        )

        http_req = google_req.to_http_request(
            descriptor=descriptor,
            access_token=access_token,
            token_type=token_type,
        )

        http_params = {
            "method": http_req.method,
            "url": http_req.url,
            "headers": dict(http_req.headers),
            "query_params": dict(http_req.query_params),
            "timeout": http_req.timeout,
        }
        if http_req.body is not None:
            http_params["body"] = http_req.body
            http_params["content_type"] = http_req.content_type

        http_context = AdapterContext.build(
            execution_session_id=context.execution_session_id,
            execution_task_id=context.execution_task_id,
            action=context.action,
            params=http_params,
            config=context.config,
            credentials={},
            logger=context.logger,
        )

        result = await self._http.execute(http_context)
        return self._postprocess_result(result, descriptor)

    def _postprocess_result(
        self,
        result: AdapterResult,
        descriptor: GoogleServiceDescriptor,
    ) -> AdapterResult:
        data: dict[str, Any] = dict(result.data) if result.data else {}
        metadata: dict[str, Any] = dict(result.metadata) if result.metadata else {}
        warnings: list[str] = list(result.warnings) if result.warnings else []

        if not result.success and data:
            body = data.get("body", "")
            google_info = parse_google_error_body(body)
            status_code = data.get("status_code", 0)
            if google_info is not None:
                data["google_error"] = google_info.to_dict()
                metadata["google_status"] = google_info.status
                exception = google_info.to_exception()
                metadata["error_type"] = type(exception).__name__
                return AdapterResult(
                    success=False,
                    error=str(exception),
                    data=data,
                    metadata=metadata,
                    warnings=warnings,
                    usage=result.usage,
                )
            if status_code:
                error_cls = classify_google_status_code(status_code)
                metadata["error_type"] = error_cls.__name__

        if result.success and data:
            json_data = data.get("json")
            if isinstance(json_data, dict):
                token = next_page_token(json_data)
                if token is not None and descriptor.supports_pagination:
                    data["next_page_token"] = token

        return AdapterResult(
            success=result.success,
            data=data,
            metadata=metadata,
            warnings=warnings,
            usage=result.usage,
            error=result.error,
        )
