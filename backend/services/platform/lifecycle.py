"""Minimal application lifecycle state (PR10.6).

Small explicit state machine: ``starting`` -> ``ready`` -> ``shutting_down``,
with ``failed`` for startup failures. Read by the readiness endpoint; set by
the FastAPI lifespan.

Deliberately tiny — no event system, no dependency graph. Optional
integrations never gate readiness (the existing architecture intentionally
supports degraded-mode operation).
"""

from __future__ import annotations

_STATE = "starting"


def get_state() -> str:
    return _STATE


def is_ready() -> bool:
    return _STATE == "ready"


def is_shutting_down() -> bool:
    return _STATE == "shutting_down"


def set_starting() -> None:
    global _STATE
    _STATE = "starting"


def set_ready() -> None:
    global _STATE
    _STATE = "ready"


def set_shutting_down() -> None:
    global _STATE
    _STATE = "shutting_down"


def set_failed() -> None:
    global _STATE
    _STATE = "failed"
