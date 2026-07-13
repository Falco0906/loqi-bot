"""Rewrite history with multi-level undo support.

Stores every rewrite for each session+draft combination,
with version numbers for full version chain tracking.
"""

from datetime import datetime, timezone
from typing import Any


class RewriteEntry:
    def __init__(
        self,
        previous_text: str,
        reason: str,
        strategy: str,
        change_summary: list[str],
        version: int = 1,
        timestamp: str | None = None,
    ):
        self.previous_text = previous_text
        self.reason = reason
        self.strategy = strategy
        self.change_summary = change_summary
        self.version = version
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "previous_text": self.previous_text,
            "reason": self.reason,
            "strategy": self.strategy,
            "change_summary": self.change_summary,
            "version": self.version,
            "timestamp": self.timestamp,
        }


_history_store: dict[str, list[RewriteEntry]] = {}


def _key(session_token: str, draft_id: str) -> str:
    return f"{session_token}:{draft_id}"


def _get_next_version(session_token: str, draft_id: str) -> int:
    k = _key(session_token, draft_id)
    entries = _history_store.get(k, [])
    return len(entries) + 1


def push(
    session_token: str,
    draft_id: str,
    previous_text: str,
    reason: str,
    strategy: str = "",
    change_summary: list[str] | None = None,
) -> int:
    """Record a rewrite operation. Returns the new version number."""
    k = _key(session_token, draft_id)
    if k not in _history_store:
        _history_store[k] = []
    version = len(_history_store[k]) + 1
    _history_store[k].append(
        RewriteEntry(
            previous_text=previous_text,
            reason=reason,
            strategy=strategy,
            change_summary=change_summary or [],
            version=version,
        )
    )
    return version


def undo(session_token: str, draft_id: str) -> RewriteEntry | None:
    """Pop the most recent rewrite entry and return it.

    Returns None if there is no history for this draft.
    """
    k = _key(session_token, draft_id)
    entries = _history_store.get(k, [])
    if not entries:
        return None
    return entries.pop()


def get_version(session_token: str, draft_id: str, version: int) -> RewriteEntry | None:
    """Get a specific version from history."""
    k = _key(session_token, draft_id)
    entries = _history_store.get(k, [])
    for e in entries:
        if e.version == version:
            return e
    return None


def get_history(session_token: str, draft_id: str) -> list[dict]:
    """Return the full rewrite history for a draft (most recent first)."""
    k = _key(session_token, draft_id)
    entries = _history_store.get(k, [])
    return [e.to_dict() for e in reversed(entries)]


def get_current_version(session_token: str, draft_id: str) -> int:
    """Return the current version number (total rewrites + 1 for original)."""
    k = _key(session_token, draft_id)
    entries = _history_store.get(k, [])
    return len(entries) + 1


def clear(session_token: str, draft_id: str) -> None:
    """Clear all history for a draft."""
    k = _key(session_token, draft_id)
    _history_store.pop(k, None)


def clear_session(session_token: str) -> None:
    """Clear all history for a session."""
    global _history_store
    _history_store = {k: v for k, v in _history_store.items() if not k.startswith(f"{session_token}:")}
