"""Bounded, classified persistence retry (PR10.8).

Single small policy used by Supabase write/read paths:

- only transient, idempotent-safe failures are retried (network errors,
  timeouts, HTTP 5xx, 429)
- authentication/authorization and other 4xx errors are fatal and never
  retried
- bounded attempts with exponential backoff and jitter; no infinite loops
- errors propagate to the caller after the budget is exhausted

Callers must only use this for operations that are safe to retry
(idempotent writes, reads, deletes). Never wrap a non-idempotent op.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 0.25
DEFAULT_MAX_DELAY = 2.0

T = TypeVar("T")


def _status_code(error: BaseException) -> int | None:
    """Extract an HTTP status code from common client exception shapes."""
    response = getattr(error, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if status is not None:
            return int(status)
    status = getattr(error, "status_code", None)
    if status is not None:
        return int(status)
    return None


def classify_retryable(error: BaseException) -> bool:
    """Return True when ``error`` looks like a transient failure worth retrying."""
    status = _status_code(error)
    if status is not None:
        if status >= 500 or status == 429:
            return True
        return False  # 4xx (incl. 401/403) are not transient DB failures

    import httpx

    if isinstance(error, (
        httpx.TransportError,
        httpx.NetworkError,
        httpx.TimeoutException,
        httpx.ConnectError,
    )):
        return True
    if isinstance(error, (ConnectionError, TimeoutError, OSError)):
        return True
    # Unknown exception type (e.g. PostgREST APIError with no HTTP status) —
    # be conservative: do not retry.
    return False


def _sleep_with_jitter(seconds: float) -> None:
    time.sleep(seconds + random.uniform(0, seconds * 0.2))


async def _asleep_with_jitter(seconds: float) -> None:
    await asyncio.sleep(seconds + random.uniform(0, seconds * 0.2))


async def retry_async(
    factory: Callable[[], Awaitable[T]],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    category: str = "",
) -> T:
    """Await ``factory()``, retrying transient failures with backoff+jitter.

    ``factory`` must be idempotent-safe. The last error is re-raised after
    the budget is exhausted.
    """
    last_error: BaseException | None = None
    for attempt in range(attempts):
        try:
            return await factory()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            last_error = error
            if not classify_retryable(error) or attempt + 1 >= attempts:
                if classify_retryable(error):
                    logger.warning(
                        "persistence_retry_exhausted category=%s attempts=%d error_type=%s",
                        category, attempts, type(error).__name__,
                    )
                raise
            delay = min(max_delay, base_delay * (2 ** attempt))
            logger.warning(
                "persistence_retry category=%s attempt=%d delay=%.2f error_type=%s",
                category, attempt + 1, delay, type(error).__name__,
            )
            await _asleep_with_jitter(delay)
    assert last_error is not None
    raise last_error


def retry_sync(
    factory: Callable[[], T],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    category: str = "",
) -> T:
    """Synchronous wrapper of :func:`retry_async` for blocking call sites."""
    last_error: BaseException | None = None
    for attempt in range(attempts):
        try:
            return factory()
        except Exception as error:  # noqa: BLE001
            last_error = error
            if not classify_retryable(error) or attempt + 1 >= attempts:
                if classify_retryable(error):
                    logger.warning(
                        "persistence_retry_exhausted category=%s attempts=%d error_type=%s",
                        category, attempts, type(error).__name__,
                    )
                raise
            delay = min(max_delay, base_delay * (2 ** attempt))
            logger.warning(
                "persistence_retry category=%s attempt=%d delay=%.2f error_type=%s",
                category, attempt + 1, delay, type(error).__name__,
            )
            _sleep_with_jitter(delay)
    assert last_error is not None
    raise last_error
