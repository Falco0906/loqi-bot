"""Workflow Retry — retry policies and error classification.

Supports:
- Immediate retry
- Fixed delay retry
- Exponential backoff

Only retries retryable errors.
Never retries validation failures.
"""

from enum import Enum
from typing import Optional


class RetryPolicy(str, Enum):
    IMMEDIATE = "immediate"
    FIXED_DELAY = "fixed_delay"
    EXPONENTIAL_BACKOFF = "exponential_backoff"


class ErrorClass(str, Enum):
    RETRYABLE = "retryable"
    FATAL = "fatal"


DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 2.0
DEFAULT_POLICY = RetryPolicy.EXPONENTIAL_BACKOFF

RETRYABLE_PATTERNS = [
    "timeout",
    "timed out",
    "connection",
    "network",
    "temporary",
    "rate limit",
    "429",
    "503",
    "502",
    "504",
    "too many requests",
    "service unavailable",
    "internal server error",
    "try again",
    "retry",
    "throttl",
    "unavailable",
    "server error",
    "gateway",
]


FATAL_PATTERNS = [
    "validation",
    "not found",
    "404",
    "400",
    "401",
    "403",
    "permission",
    "forbidden",
    "unauthorized",
    "invalid input",
    "bad request",
    "already exists",
]


def classify_error(error_message: str) -> ErrorClass:
    msg = error_message.lower()
    for pattern in FATAL_PATTERNS:
        if pattern in msg:
            return ErrorClass.FATAL
    for pattern in RETRYABLE_PATTERNS:
        if pattern in msg:
            return ErrorClass.RETRYABLE
    return ErrorClass.RETRYABLE


def get_retry_delay(policy: RetryPolicy, attempt: int, base_delay: float = DEFAULT_BASE_DELAY) -> float:
    if policy == RetryPolicy.IMMEDIATE:
        return 0.0
    if policy == RetryPolicy.FIXED_DELAY:
        return base_delay
    if policy == RetryPolicy.EXPONENTIAL_BACKOFF:
        return base_delay * (2 ** (attempt - 1))
    return base_delay


def should_retry(attempt: int, max_retries: int) -> bool:
    return attempt < max_retries


class RetryState:
    def __init__(self, max_retries: int = DEFAULT_MAX_RETRIES, policy: RetryPolicy = DEFAULT_POLICY):
        self.max_retries = max_retries
        self.policy = policy
        self.current_attempt = 0
        self.base_delay = DEFAULT_BASE_DELAY

    def next_delay(self) -> float:
        self.current_attempt += 1
        return get_retry_delay(self.policy, self.current_attempt, self.base_delay)

    def can_retry(self) -> bool:
        return self.current_attempt < self.max_retries
