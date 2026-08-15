"""Minimal server-side OAuth state (CSRF) protection (PR10.7).

The Gmail web OAuth callback must only proceed for a state token that this
process issued. State tokens are random, single-use, time-limited, and stored
in-memory (per-instance). A lost token after restart fails the callback safely
(no fallback to unverified identity).
"""

from __future__ import annotations

import secrets
import time
from typing import Any

STATE_TTL_SECONDS = 600
_states: dict[str, dict[str, Any]] = {}


def issue_state(user_id: str) -> str:
    """Create a single-use state token bound to ``user_id``."""
    _prune()
    token = secrets.token_urlsafe(32)
    _states[token] = {"user_id": user_id, "created_at": time.time()}
    return token


def consume_state(state: str) -> str | None:
    """Verify + consume a state token, returning the bound user id or None."""
    if not state:
        return None
    entry = _states.pop(state, None)
    if entry is None:
        return None
    if time.time() - entry.get("created_at", 0) > STATE_TTL_SECONDS:
        return None
    return entry.get("user_id") or None


def _prune() -> None:
    now = time.time()
    expired = [
        token for token, entry in _states.items()
        if now - entry.get("created_at", 0) > STATE_TTL_SECONDS
    ]
    for token in expired:
        _states.pop(token, None)
