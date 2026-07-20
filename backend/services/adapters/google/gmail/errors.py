from __future__ import annotations

from services.adapters.google.errors import GoogleApiError


class GmailError(GoogleApiError):
    """Base exception for all Gmail adapter failures."""


class MessageNotFoundError(GmailError):
    """Raised when a requested message does not exist."""


class ThreadNotFoundError(GmailError):
    """Raised when a requested thread does not exist."""


class LabelNotFoundError(GmailError):
    """Raised when a requested label does not exist."""


class InvalidQueryError(GmailError):
    """Raised when a Gmail search query is invalid."""
