from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.adapters.google.services import GoogleServiceDescriptor
from services.adapters.http.models import HttpRequest


@dataclass(frozen=True)
class GoogleApiRequest:
    """Immutable request model for a Google API call.

    Converts to an ``HttpRequest`` via ``to_http_request()``,
    which resolves the service descriptor and builds the full URL.
    """

    service: str
    resource: str
    version: str = ""
    method: str = "GET"
    query: dict[str, str] = field(default_factory=dict)
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0

    def to_http_request(
        self,
        descriptor: GoogleServiceDescriptor,
        access_token: str = "",
        token_type: str = "Bearer",
    ) -> HttpRequest:
        """Convert to an ``HttpRequest`` with full URL and auth headers."""
        url = descriptor.build_url(version=self.version, resource=self.resource)
        headers = dict(self.headers)
        if access_token:
            headers["Authorization"] = f"{token_type} {access_token}"
        if "content-type" not in {k.lower() for k in headers}:
            headers["Content-Type"] = "application/json"
        return HttpRequest(
            method=self.method,
            url=url,
            headers=headers,
            query_params=dict(self.query),
            body=self.body,
            timeout=self.timeout,
            content_type="application/json",
        )


@dataclass(frozen=True)
class GoogleApiResponse:
    """Immutable response model wrapping a Google API result.

    Provides convenience helpers for common Google response fields.
    """

    data: dict[str, Any]
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status_code < 400

    def next_page_token(self) -> str | None:
        return self.data.get("nextPageToken")

    def etag(self) -> str | None:
        return self.data.get("etag")

    def kind(self) -> str | None:
        return self.data.get("kind")

    def resource_id(self) -> str | None:
        return self.data.get("id")

    def __repr__(self) -> str:
        return (
            f"GoogleApiResponse(status_code={self.status_code}, "
            f"kind={self.kind()!r})"
        )
