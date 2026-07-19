from __future__ import annotations

from typing import Protocol

import httpx

from services.adapters.http.exceptions import (
    ConnectionError as HttpConnectionError,
    HttpStatusError,
    RequestTimeoutError,
    SerializationError,
)
from services.adapters.http.models import HttpRequest, HttpResponse


class HttpTransport(Protocol):
    """Protocol for HTTP transport implementations.

    Implementations handle the low-level network communication,
    allowing the adapter to remain transport-agnostic.
    """

    async def send(self, request: HttpRequest) -> HttpResponse:
        """Send an HTTP request and return a response.

        Raises transport-specific exceptions mapped to the HTTP
        adapter's exception hierarchy.
        """


class HttpxTransport:
    """HTTP transport implementation using the httpx library.

    Uses ``httpx.AsyncClient`` with configurable client options.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def send(self, request: HttpRequest) -> HttpResponse:
        client = self._client or httpx.AsyncClient()
        if self._client is None:
            async with client as cm:
                return await self._do_send(cm, request)
        return await self._do_send(client, request)

    async def _do_send(
        self, client: httpx.AsyncClient, request: HttpRequest
    ) -> HttpResponse:
        try:
            httpx_request = client.build_request(
                method=request.method,
                url=request.url,
                headers=request.headers,
                params=request.query_params or None,
                content=_resolve_body(request),
                timeout=request.timeout,
            )
            httpx_response = await client.send(httpx_request)
        except httpx.TimeoutException as exc:
            raise RequestTimeoutError(
                f"Request to {request.url} timed out after {request.timeout}s: {exc}"
            ) from exc
        except httpx.ConnectError as exc:
            raise HttpConnectionError(
                f"Failed to connect to {request.url}: {exc}"
            ) from exc
        except httpx.RemoteProtocolError as exc:
            raise HttpConnectionError(
                f"Protocol error communicating with {request.url}: {exc}"
            ) from exc
        except httpx.DecodingError as exc:
            raise SerializationError(
                f"Failed to decode response from {request.url}: {exc}"
            ) from exc

        return self._build_response(httpx_response)

    def _build_response(self, response: httpx.Response) -> HttpResponse:
        http_response = HttpResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=response.content,
            elapsed=response.elapsed.total_seconds(),
            content_type=response.headers.get("content-type", ""),
        )

        if http_response.is_client_error() or http_response.is_server_error():
            raise HttpStatusError(
                message=f"HTTP {response.status_code} for {response.url}",
                status_code=response.status_code,
                body=response.text,
                headers=dict(response.headers),
            )

        return http_response


def _resolve_body(request: HttpRequest) -> bytes | None:
    """Resolve the request body to bytes or None."""
    if request.body is None:
        return None
    if isinstance(request.body, bytes):
        return request.body
    if isinstance(request.body, str):
        return request.body.encode("utf-8")
    if isinstance(request.body, (dict, list)):
        import json as _json

        try:
            return _json.dumps(request.body).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise SerializationError(
                f"Failed to serialize request body: {exc}"
            ) from exc
    try:
        return str(request.body).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SerializationError(
            f"Failed to serialize request body: {exc}"
        ) from exc
