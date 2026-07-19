from __future__ import annotations

from typing import Any


def next_page_token(response_data: dict[str, Any]) -> str | None:
    """Extract the ``nextPageToken`` from a Google API response dict.

    Returns None if no pagination token is present.
    """
    return response_data.get("nextPageToken")


def page_token_param(token: str) -> dict[str, str]:
    """Create the ``pageToken`` query parameter dict for pagination.

    Usage::

        params["query"] = page_token_param("token123")
    """
    return {"pageToken": token}


def max_results_param(max_results: int) -> dict[str, str]:
    """Create the ``maxResults`` query parameter dict.

    Usage::

        params["query"] = max_results_param(100)
    """
    return {"maxResults": str(max_results)}


def has_more_pages(response_data: dict[str, Any]) -> bool:
    """Check whether a Google API response has additional pages.

    Returns True if ``nextPageToken`` is present and non-empty.
    """
    token = next_page_token(response_data)
    return token is not None and token != ""
